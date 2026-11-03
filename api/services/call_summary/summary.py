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


class BookingAction(StrEnum):
    # Each value is also the flag the calendar tool's result sets on success.
    BOOKED = "booked"
    CANCELLED = "cancelled"


# Calendar tools by their MCP name. The agent sees them namespaced as
# ``mcp__<tool>__<name>``.
_BOOKING_TOOLS = {
    "book_appointment": BookingAction.BOOKED,
    "cancel_appointment": BookingAction.CANCELLED,
}


@dataclass(frozen=True, slots=True)
class BookingChange:
    action: BookingAction
    # Known for bookings: the slot id is the appointment's ISO start time.
    starts_at: datetime | None
    caller_name: str | None
    caller_phone: str | None
    # What the calendar told the caller, e.g. "Your appointment for ... is
    # cancelled."; the only description a cancellation has.
    confirmation: str | None


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
    callback_number = _text(captured.get(CALLBACK_NUMBER_KEY))
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


def booking_changes(
    realtime_events: Sequence[Mapping[str, Any]],
) -> tuple[BookingChange, ...]:
    """The bookings and cancellations the calendar confirmed, in call order.

    Attempts the calendar refused (the slot had gone, nothing to cancel) are
    left out: the caller was told and nothing changed.
    """
    pending: dict[str, tuple[BookingAction, Mapping[str, Any]]] = {}
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
            action = _booking_action(payload.get("function_name"))
            arguments = payload.get("arguments")
            if action is not None:
                pending[call_id] = (
                    action,
                    arguments if isinstance(arguments, Mapping) else {},
                )
        elif kind == RealtimeFeedbackType.FUNCTION_CALL_END.value:
            started = pending.pop(call_id, None)
            if started is None:
                continue
            action, arguments = started
            result = _json_object(payload.get("result"))
            if result.get(action.value) is True:
                changes.append(_change(action, arguments, result))
    return tuple(changes)


def _booking_action(function_name: object) -> BookingAction | None:
    if not isinstance(function_name, str):
        return None
    return _BOOKING_TOOLS.get(function_name.rsplit("__", 1)[-1])


def _change(
    action: BookingAction, arguments: Mapping[str, Any], result: Mapping[str, Any]
) -> BookingChange:
    return BookingChange(
        action=action,
        starts_at=_aware_datetime(arguments.get("slot_id")),
        caller_name=_text(arguments.get("caller_name")),
        caller_phone=_text(arguments.get("caller_phone")),
        confirmation=_text(result.get("say")),
    )


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
