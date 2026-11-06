"""What happened on a finished call, read from the stored run.

Pure functions over the run's stored JSON (``mode``, ``call_type``,
``gathered_context``, ``logs``, ``usage_info``); no I/O. The service decides
who hears about it; this module only decides what happened.
``app-doc/notifications.md`` explains each rule in plain words.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from pipecat.utils.enums import RealtimeFeedbackType

from api.enums import (
    WORKFLOW_RUN_MODES_BY_CHANNEL,
    CallType,
    TelephonyCallStatus,
    WorkflowRunChannel,
)

# A caller who hangs up this soon after the call starts was not helped, even
# if they said a word ("hello?") first.
SHORT_HANGUP_SECONDS = 15

_TELEPHONY_MODES = frozenset(
    WORKFLOW_RUN_MODES_BY_CHANNEL[WorkflowRunChannel.TELEPHONY.value]
)

# Statuses written when the call never reached the agent (the carrier's
# status callback, or a call start that was rejected).
_NEVER_CONNECTED = frozenset(
    {
        TelephonyCallStatus.NO_ANSWER.value,
        TelephonyCallStatus.BUSY.value,
        TelephonyCallStatus.FAILED.value,
        TelephonyCallStatus.CANCELED.value,
        TelephonyCallStatus.ERROR.value,
    }
)
# The call broke on our side part-way through (EndTaskReason values).
_FAULTS = frozenset({"pipeline_error", "unexpected_error"})
_USER_HANGUP = "user_hangup"
# Handed to a person who answered (EndTaskReason.TRANSFER_CALL).
_TRANSFERRED = "transfer_call"
_FUNCTION_CALL_END = RealtimeFeedbackType.FUNCTION_CALL_END.value

MESSAGE_FIELDS = ("caller_name", "callback_number", "call_reason")


class CallEvent(StrEnum):
    BOOKING_MADE = "booking_made"
    MESSAGE_TAKEN = "message_taken"
    MISSED_CALL = "missed_call"


class MissedReason(StrEnum):
    NEVER_CONNECTED = "never_connected"
    FAULT = "fault"
    SILENT = "silent"
    SHORT_HANGUP = "short_hangup"
    TRANSFER_UNANSWERED = "transfer_unanswered"


@dataclass(frozen=True, slots=True)
class ConfirmedBooking:
    """A booking the calendar tool said it made (``booked: true``), or moved
    to a new time (``reschedule_appointment`` outcome ``moved`` or
    ``old_not_cancelled``).

    ``start`` is the calendar's ``starts_at`` for that result, else the
    ``slot_id`` argument (the calendar books exactly the slot it is given;
    the id is that slot's ISO time). ``party_size`` is the argument the
    calendar stored on the event. None of it is the LLM's after-call
    extraction.
    """

    event_id: str
    start: datetime
    party_size: int | None
    caller_name: str | None
    caller_phone: str | None
    # A booking made on an earlier call that this call moved to ``start``.
    moved: bool = False


@dataclass(frozen=True, slots=True)
class CancelledBooking:
    """A booking made on an earlier call that this call cancelled. ``start``
    is the cancelled time, when the calendar reported it."""

    event_id: str
    start: datetime | None


@dataclass(frozen=True, slots=True)
class CalendarActivity:
    """What the calendar confirmed on one call, in call order."""

    # Bookings made or moved on this call that still stand.
    bookings: list[ConfirmedBooking] = field(default_factory=list)
    # Bookings from earlier calls that this call cancelled.
    cancelled: list[CancelledBooking] = field(default_factory=list)
    # A move booked the new time but could not remove the old booking.
    old_booking_kept: bool = False


@dataclass(frozen=True, slots=True)
class CallOutcome:
    event: CallEvent | None
    bookings: list[ConfirmedBooking] = field(default_factory=list)
    cancelled: list[CancelledBooking] = field(default_factory=list)
    old_booking_kept: bool = False
    missed_reason: MissedReason | None = None
    # The agent recorded booking_outcome "booked" but no calendar tool
    # confirmed a booking: told to the business as a message, never as a
    # booking, and the caller gets no text.
    unconfirmed_booking_claim: bool = False


def is_phone_call(mode: str | None, call_type: str | None) -> bool:
    """Inbound phone calls: every notification. Browser test calls (WebRTC)
    and text chats never notify; for outbound calls see
    ``is_outbound_phone_call``."""
    return mode in _TELEPHONY_MODES and call_type == CallType.INBOUND.value


def is_outbound_phone_call(mode: str | None, call_type: str | None) -> bool:
    """Outbound phone calls (e.g. appointment reminders): only a booking
    change or a message emails the business; nothing counts as missed and
    the person called is never texted."""
    return mode in _TELEPHONY_MODES and call_type == CallType.OUTBOUND.value


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _parse_json_object(value: Any) -> Mapping[str, Any] | None:
    """A tool result as a dict. MCP results are stored as the tool's JSON
    text; other tools store a dict."""
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, Mapping) else None
    return None


def _tool_is(function_name: Any, tool: str) -> bool:
    # MCP functions are namespaced ``mcp__<server>__<tool>``.
    name = _text(function_name)
    return name == tool or name.endswith(f"__{tool}")


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
        return number if number > 0 else None
    return None


def _aware_time(value: Any) -> datetime | None:
    """An ISO time with an offset; a naive or unreadable one is None (there
    is no zone to read it in)."""
    try:
        moment = datetime.fromisoformat(_text(value))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


# reschedule_appointment outcomes after which the new time is booked.
_MOVED_OUTCOMES = frozenset({"moved", "old_not_cancelled"})


def calendar_activity(tool_results: Sequence[Any]) -> CalendarActivity:
    """Bookings made, moved and cancelled on one call, as the calendar
    confirmed them. Refused attempts (slot gone, nothing found, handed off)
    changed nothing and are left out."""
    bookings: dict[str, ConfirmedBooking] = {}
    cancelled: list[CancelledBooking] = []
    old_kept = False
    for record in tool_results or ():
        if not isinstance(record, Mapping) or record.get("status") != "completed":
            continue
        name = record.get("function_name")
        arguments = record.get("arguments")
        if not isinstance(arguments, Mapping):
            arguments = {}
        result = _parse_json_object(record.get("result"))
        if result is None:
            continue
        if _tool_is(name, "book_appointment"):
            event_id = _text(result.get("event_id"))
            if result.get("booked") is not True or not event_id:
                continue
            start = _aware_time(result.get("starts_at")) or _aware_time(
                arguments.get("slot_id")
            )
            if start is None:
                # Without the time the calendar accepted there is nothing
                # trustworthy to confirm.
                continue
            bookings.pop(event_id, None)
            bookings[event_id] = ConfirmedBooking(
                event_id=event_id,
                start=start,
                party_size=_positive_int(arguments.get("party_size")),
                caller_name=_text(arguments.get("caller_name")) or None,
                caller_phone=_text(arguments.get("caller_phone")) or None,
            )
        elif _tool_is(name, "reschedule_appointment"):
            new_id = _text(result.get("event_id"))
            if _text(result.get("outcome")) not in _MOVED_OUTCOMES or not new_id:
                continue
            start = _aware_time(result.get("starts_at")) or _aware_time(
                arguments.get("slot_id")
            )
            if start is None:
                continue
            old_kept = old_kept or result.get("outcome") == "old_not_cancelled"
            # Moving a booking made on this call keeps its details; one from
            # an earlier call is reported as a move.
            previous = bookings.pop(_text(arguments.get("event_id")), None)
            bookings.pop(new_id, None)
            bookings[new_id] = ConfirmedBooking(
                event_id=new_id,
                start=start,
                party_size=previous.party_size if previous else None,
                caller_name=previous.caller_name if previous else None,
                caller_phone=previous.caller_phone if previous else None,
                moved=previous.moved if previous else True,
            )
        elif _tool_is(name, "cancel_appointment") and result.get("cancelled") is True:
            event_id = _text(arguments.get("event_id"))
            previous = bookings.pop(event_id, None)
            if previous is None or previous.moved:
                # A booking from an earlier call (or one this call moved from
                # an earlier call) is gone: the business must know.
                cancelled.append(
                    CancelledBooking(
                        event_id=event_id,
                        start=_aware_time(result.get("starts_at"))
                        or (previous.start if previous else None),
                    )
                )
    return CalendarActivity(
        bookings=list(bookings.values()),
        cancelled=cancelled,
        old_booking_kept=old_kept,
    )


def confirmed_bookings(tool_results: Sequence[Any]) -> list[ConfirmedBooking]:
    """Bookings the calendar confirmed (made or moved) and that were not
    cancelled later in the same call, in the order they were made."""
    return calendar_activity(tool_results).bookings


def _stored_function_result(value: Any) -> Mapping[str, Any] | None:
    """The call log stores ``str(result)``, a Python repr for dicts. Parsed
    with ``literal_eval``, which reads literals only and never runs code."""
    parsed = _parse_json_object(value)
    if parsed is not None or not isinstance(value, str):
        return parsed
    try:
        literal = ast.literal_eval(value)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None
    return literal if isinstance(literal, Mapping) else None


def transfer_failed(logs: Mapping[str, Any] | None) -> bool:
    """A transfer to a person was tried and did not connect (no answer,
    busy, no number set up). Transfer tools are not in ``tool_results``;
    their results are in the call log."""
    for event in (logs or {}).get("realtime_feedback_events") or []:
        if not isinstance(event, Mapping) or event.get("type") != _FUNCTION_CALL_END:
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        result = _stored_function_result(payload.get("result"))
        if result is not None and result.get("status") == "transfer_failed":
            return True
    return False


def message_details(gathered: Mapping[str, Any]) -> dict[str, str]:
    """The message fields the agent captured, non-empty ones only."""
    return {
        key: _text(gathered.get(key))
        for key in MESSAGE_FIELDS
        if _text(gathered.get(key))
    }


def call_duration_seconds(usage_info: Mapping[str, Any] | None) -> float | None:
    value = (usage_info or {}).get("call_duration_seconds")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def missed_reason(
    gathered: Mapping[str, Any],
    logs: Mapping[str, Any] | None,
    usage_info: Mapping[str, Any] | None,
) -> MissedReason | None:
    """Why an inbound call with no booking and no message counts as missed,
    or None when the caller was looked after (e.g. their question was
    answered, or a person took the call)."""
    status = _text(gathered.get("call_status")) or _text(
        gathered.get("call_disposition")
    )
    if status == _TRANSFERRED:
        return None
    if status in _NEVER_CONNECTED:
        return MissedReason.NEVER_CONNECTED
    if status in _FAULTS:
        return MissedReason.FAULT
    tags = gathered.get("call_tags")
    if not isinstance(tags, list) or "user_speech" not in tags:
        return MissedReason.SILENT
    duration = call_duration_seconds(usage_info)
    if (
        status == _USER_HANGUP
        and duration is not None
        and duration < SHORT_HANGUP_SECONDS
    ):
        return MissedReason.SHORT_HANGUP
    if transfer_failed(logs):
        return MissedReason.TRANSFER_UNANSWERED
    return None


def classify_call(
    *,
    gathered_context: Mapping[str, Any] | None,
    logs: Mapping[str, Any] | None,
    usage_info: Mapping[str, Any] | None,
) -> CallOutcome:
    """Booking made, moved or cancelled, else message taken, else missed
    call, else nothing.

    Only meaningful for runs ``is_phone_call`` or ``is_outbound_phone_call``
    accepts.
    """
    gathered = gathered_context or {}
    activity = calendar_activity(gathered.get("tool_results") or [])
    if activity.bookings or activity.cancelled:
        return CallOutcome(
            event=CallEvent.BOOKING_MADE,
            bookings=activity.bookings,
            cancelled=activity.cancelled,
            old_booking_kept=activity.old_booking_kept,
        )

    booking_outcome = _text(gathered.get("booking_outcome")).lower()
    claimed_booking = booking_outcome == "booked"
    if message_details(gathered) or booking_outcome == "requested" or claimed_booking:
        return CallOutcome(
            event=CallEvent.MESSAGE_TAKEN, unconfirmed_booking_claim=claimed_booking
        )

    reason = missed_reason(gathered, logs, usage_info)
    if reason is not None:
        return CallOutcome(event=CallEvent.MISSED_CALL, missed_reason=reason)
    return CallOutcome(event=None)
