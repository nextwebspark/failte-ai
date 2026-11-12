"""What happened on each inbound phone call, in the words Home uses.

Pure functions over the rows ``DashboardClient.get_inbound_calls_for_dashboard``
returns (plus the call log for calls whose log mentions a failed transfer); no
I/O. Every rule reads something the call stored; nothing is estimated.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from api.db.dashboard_client import FOLLOW_UP_KINDS_ANNOTATION
from api.services.call_notifications.outcome import (
    CallEvent,
    MissedReason,
    classify_call,
    missed_reason,
    transfer_failed,
)
from api.services.call_review.review import stored_review
from api.services.calls.lines_busy import (
    LinesBusyAction,
    forward_answered,
    is_lines_busy,
    lines_busy_outcome,
    planned_action,
    voicemail_seconds,
)
from api.services.reports.daily_report import is_transferred

# A call the engine has not marked finished is "in progress" only this long;
# after that it is read like any other call (the process may have died).
IN_PROGRESS_FOR = timedelta(hours=1)
# A turned-away call taking a voicemail (or just told the lines are busy) is
# over in a couple of minutes; one being forwarded may last as long as any.
LINES_BUSY_IN_PROGRESS_FOR = timedelta(minutes=10)

CALLBACK_DISPOSITION = "callback_requested"

# Numbers carriers send for a withheld caller id.
_WITHHELD = frozenset({"anonymous", "unknown", "restricted", "private", "unavailable"})


class CallResult(StrEnum):
    """One outcome per call, checked in this order."""

    IN_PROGRESS = "in_progress"
    # The engine says the call ended with a person taking it.
    PASSED_TO_TEAM = "passed_to_team"
    # The calendar confirmed a booking made, moved or cancelled on the call.
    BOOKING_MADE = "booking_made"
    # The agent tried to pass the call to a person and nobody picked up
    # (the transfer tool's result in the call log).
    TRANSFER_NOT_ANSWERED = "transfer_not_answered"
    # The caller asked to be called back (outcome ``callback_requested``),
    # left a number to ring them on, or asked for a booking the agent could
    # only pass on (``booking_outcome`` "requested"). A name or a reason alone
    # doesn't count: the agent writes those down on ordinary calls too.
    CALLBACK_REQUESTED = "callback_requested"
    # The engine heard no speech from the caller (no ``user_speech`` tag).
    HUNG_UP_SILENT = "hung_up_silent"
    # The caller spoke, then hung up within ``SHORT_HANGUP_SECONDS``.
    HUNG_UP_EARLY = "hung_up_early"
    # The carrier reported no answer, busy, failed or cancelled.
    NOT_CONNECTED = "not_connected"
    # The call broke on our side part-way through.
    CALL_DROPPED = "call_dropped"
    # Every line was busy (the business's calls-at-once limit): the caller
    # never reached the agent, and nobody on the team answered a forward.
    # They may have left a voicemail.
    LINES_BUSY = "lines_busy"
    # Spoke with the agent, no person needed.
    HANDLED = "handled"


# Calls the agent dealt with from start to finish.
HANDLED_RESULTS = frozenset({CallResult.HANDLED, CallResult.BOOKING_MADE})
# Calls where the caller reached nobody, neither the agent nor a person.
UNREACHED_RESULTS = frozenset(
    {
        CallResult.TRANSFER_NOT_ANSWERED,
        CallResult.HUNG_UP_SILENT,
        CallResult.HUNG_UP_EARLY,
        CallResult.NOT_CONNECTED,
        CallResult.CALL_DROPPED,
        CallResult.LINES_BUSY,
    }
)

_MISSED_RESULT = {
    MissedReason.SILENT: CallResult.HUNG_UP_SILENT,
    MissedReason.SHORT_HANGUP: CallResult.HUNG_UP_EARLY,
    MissedReason.NEVER_CONNECTED: CallResult.NOT_CONNECTED,
    MissedReason.FAULT: CallResult.CALL_DROPPED,
    MissedReason.TRANSFER_UNANSWERED: CallResult.TRANSFER_NOT_ANSWERED,
}


@dataclass(frozen=True, slots=True)
class CallView:
    run_id: int
    workflow_id: int
    workflow_name: str
    created_at: datetime
    result: CallResult
    duration_seconds: float | None
    has_recording: bool
    caller_number: str | None
    caller_name: str | None
    call_reason: str | None
    callback_number: str | None
    # The follow-up mark stored on the call (``annotations.follow_up``).
    follow_up_mark: Mapping[str, Any] | None
    # The call review (``annotations.call_review``), when written.
    review: Mapping[str, Any] | None = None
    # Marks per call-review follow-up kind (``annotations.follow_up_kinds``).
    follow_up_marks: Mapping[str, Mapping[str, Any]] | None = None
    # A call turned away because every line was busy: what came of it
    # (``calls.lines_busy.LinesBusyOutcome``) and the voicemail's length.
    lines_busy: str | None = None
    voicemail_seconds: int | None = None


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def duration_seconds(usage_info: Mapping[str, Any] | None) -> float | None:
    value = (usage_info or {}).get("call_duration_seconds")
    if isinstance(value, bool):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def caller_number(initial_context: Mapping[str, Any] | None) -> str | None:
    """The caller's number on an inbound call, None when withheld."""
    number = _text((initial_context or {}).get("caller_number"))
    if number is None or number.lower() in _WITHHELD:
        return None
    return number


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def call_result(
    *,
    is_completed: bool,
    created_at: datetime,
    gathered_context: Mapping[str, Any] | None,
    usage_info: Mapping[str, Any] | None,
    logs: Mapping[str, Any] | None,
    now: datetime,
) -> CallResult:
    gathered = gathered_context or {}
    if is_lines_busy(gathered):
        return _lines_busy_result(gathered, is_completed, created_at, now)
    if not is_completed and now - _aware(created_at) < IN_PROGRESS_FOR:
        return CallResult.IN_PROGRESS
    if is_transferred(gathered):
        return CallResult.PASSED_TO_TEAM
    outcome = classify_call(gathered_context=gathered, logs=logs, usage_info=usage_info)
    if outcome.event == CallEvent.BOOKING_MADE:
        return CallResult.BOOKING_MADE
    # Checked before the message: the caller wanted a person and didn't get
    # one, even if the agent then took their number.
    if transfer_failed(logs):
        return CallResult.TRANSFER_NOT_ANSWERED
    if wants_callback(gathered):
        return CallResult.CALLBACK_REQUESTED
    reason = missed_reason(gathered, logs, usage_info)
    if reason is not None:
        return _MISSED_RESULT[reason]
    return CallResult.HANDLED


def _lines_busy_result(
    gathered: Mapping[str, Any], is_completed: bool, created_at: datetime, now: datetime
) -> CallResult:
    """A turned-away call: put through to someone on the team, or not."""
    if forward_answered(gathered):
        return CallResult.PASSED_TO_TEAM
    still_on = (
        IN_PROGRESS_FOR
        if planned_action(gathered) == LinesBusyAction.FORWARD
        else LINES_BUSY_IN_PROGRESS_FOR
    )
    if not is_completed and now - _aware(created_at) < still_on:
        return CallResult.IN_PROGRESS
    return CallResult.LINES_BUSY


def wants_callback(gathered: Mapping[str, Any]) -> bool:
    return (
        gathered.get("mapped_call_disposition") == CALLBACK_DISPOSITION
        or _text(gathered.get("callback_number")) is not None
        or (_text(gathered.get("booking_outcome")) or "").lower() == "requested"
    )


def call_view(
    row: Mapping[str, Any], logs: Mapping[str, Any] | None, now: datetime
) -> CallView:
    """One row of ``get_inbound_calls_for_dashboard`` as Home reads it.
    ``logs`` is the call log, needed only when ``row["transfer_hint"]``."""
    gathered = row.get("gathered_context") or {}
    annotations = row.get("annotations") or {}
    mark = annotations.get("follow_up")
    return CallView(
        run_id=row["id"],
        workflow_id=row["workflow_id"],
        workflow_name=row.get("workflow_name") or "",
        created_at=_aware(row["created_at"]),
        result=call_result(
            is_completed=bool(row.get("is_completed")),
            created_at=row["created_at"],
            gathered_context=gathered,
            usage_info=row.get("usage_info"),
            logs=logs,
            now=now,
        ),
        duration_seconds=duration_seconds(row.get("usage_info")),
        has_recording=bool(row.get("has_recording")),
        caller_number=caller_number(row.get("initial_context")),
        caller_name=_text(gathered.get("caller_name")),
        call_reason=_text(gathered.get("call_reason")),
        callback_number=_text(gathered.get("callback_number")),
        follow_up_mark=mark
        if isinstance(mark, Mapping) and mark.get("done_at")
        else None,
        review=stored_review(annotations),
        follow_up_marks=_kind_marks(annotations.get(FOLLOW_UP_KINDS_ANNOTATION)),
        lines_busy=(outcome := lines_busy_outcome(gathered)) and outcome.value,
        voicemail_seconds=voicemail_seconds(gathered),
    )


def _kind_marks(value: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(kind): mark
        for kind, mark in value.items()
        if isinstance(mark, Mapping) and mark.get("done_at")
    }


def number_key(number: str | None) -> str | None:
    """Digits to match one caller's calls: "+353 87 123 4567" and
    "+353871234567" are the same caller."""
    if not number:
        return None
    digits = "".join(ch for ch in number if ch.isdigit())
    return digits or None
