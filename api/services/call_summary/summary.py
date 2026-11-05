"""What a finished call left for the business: a message, booking changes, or
both. Read from the run's extracted variables and its recorded tool calls."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from pipecat.utils.enums import RealtimeFeedbackType

# The receptionist template captures these (its ``captured_fields``).
CALLER_NAME_KEY = "caller_name"
CALLBACK_NUMBER_KEY = "callback_number"
CALL_REASON_KEY = "call_reason"
# Fewer digits than this is a placeholder ("N/A", "unknown"), not a number.
MIN_CALLBACK_DIGITS = 6


class BookingAction(StrEnum):
    BOOKED = "booked"
    CANCELLED = "cancelled"
    MOVED = "moved"
    # Moved, but the old booking could not be removed: staff must delete it.
    MOVED_OLD_KEPT = "moved_old_kept"


@dataclass(frozen=True, slots=True)
class BookingTool:
    # The result field that says what happened, and the action each of its
    # values means. Any other value changed nothing in the calendar.
    result_field: str
    actions: Mapping[bool | str, BookingAction]

    def action_for(self, result: Mapping[str, Any]) -> BookingAction | None:
        value = result.get(self.result_field)
        # Only JSON booleans and strings: 1 == True must not count as booked.
        if not isinstance(value, bool | str):
            return None
        return self.actions.get(value)


# Calendar tools by their MCP name. The agent sees them namespaced as
# ``mcp__<tool>__<name>``. A new calendar action is one entry here.
BOOKING_TOOLS: Mapping[str, BookingTool] = {
    "book_appointment": BookingTool("booked", {True: BookingAction.BOOKED}),
    "cancel_appointment": BookingTool("cancelled", {True: BookingAction.CANCELLED}),
    "reschedule_appointment": BookingTool(
        "outcome",
        {
            "moved": BookingAction.MOVED,
            "old_not_cancelled": BookingAction.MOVED_OLD_KEPT,
        },
    ),
}


@dataclass(frozen=True, slots=True)
class BookingChange:
    action: BookingAction
    # The appointment's start (the new one when moved), when the calendar
    # reported it.
    starts_at: datetime | None
    caller_name: str | None
    caller_phone: str | None


@dataclass(frozen=True, slots=True)
class CallSummary:
    caller_name: str | None
    callback_number: str | None
    reason: str | None
    booking_changes: tuple[BookingChange, ...]


def extract_call_summary(
    gathered_context: Mapping[str, Any],
    realtime_events: Sequence[Mapping[str, Any]],
) -> CallSummary | None:
    """The summary worth sending, or None when the call left nothing to act on.

    A call took a message when the caller left a callback number; a name or a
    reason alone is captured on calls that only asked a question.
    """
    extracted = gathered_context.get("extracted_variables")
    captured = extracted if isinstance(extracted, Mapping) else {}
    callback_number = callback_number_of(captured.get(CALLBACK_NUMBER_KEY))
    changes = booking_changes(realtime_events)
    if callback_number is None and not changes:
        return None
    caller_name = _text(captured.get(CALLER_NAME_KEY)) or next(
        (c.caller_name for c in changes if c.caller_name), None
    )
    return CallSummary(
        caller_name=caller_name,
        callback_number=callback_number,
        reason=_text(captured.get(CALL_REASON_KEY)),
        booking_changes=changes,
    )


def callback_number_of(value: object) -> str | None:
    """The captured callback number, or None when it is not a phone number."""
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    text = _text(value)
    if text is None or sum(c.isdigit() for c in text) < MIN_CALLBACK_DIGITS:
        return None
    return text


def booking_changes(
    realtime_events: Sequence[Mapping[str, Any]],
) -> tuple[BookingChange, ...]:
    """The bookings, moves and cancellations the calendar confirmed, in call
    order.

    Attempts the calendar refused (the slot had gone, nothing to cancel or
    move) are left out: the caller was told and nothing changed.
    """
    pending: dict[str, tuple[BookingTool, Mapping[str, Any]]] = {}
    changes: list[BookingChange] = []
    for event in realtime_events:
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        call_id = payload.get("tool_call_id")
        if not isinstance(call_id, str):
            continue
        kind = event.get("type")
        if kind == RealtimeFeedbackType.FUNCTION_CALL_START.value:
            tool = _booking_tool(payload.get("function_name"))
            arguments = payload.get("arguments")
            if tool is not None:
                pending[call_id] = (
                    tool,
                    arguments if isinstance(arguments, Mapping) else {},
                )
        elif kind == RealtimeFeedbackType.FUNCTION_CALL_END.value:
            started = pending.pop(call_id, None)
            if started is None:
                continue
            tool, arguments = started
            result = _json_object(payload.get("result"))
            action = tool.action_for(result)
            if action is not None:
                changes.append(
                    BookingChange(
                        action=action,
                        starts_at=_aware_datetime(result.get("starts_at")),
                        caller_name=_text(arguments.get("caller_name")),
                        caller_phone=_text(arguments.get("caller_phone")),
                    )
                )
    return tuple(changes)


def _booking_tool(function_name: object) -> BookingTool | None:
    if not isinstance(function_name, str):
        return None
    return BOOKING_TOOLS.get(function_name.rsplit("__", 1)[-1])


def _json_object(value: object) -> Mapping[str, Any]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    # A naive time has no zone to show it in; leave it out rather than guess.
    return parsed if parsed.tzinfo is not None else None


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split()) or None
