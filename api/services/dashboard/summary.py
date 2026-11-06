"""Home's numbers, counted from stored calls. Pure functions; the loader in
``service.py`` does the reading."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from api.services.dashboard.calls import HANDLED_RESULTS, CallResult, CallView

RECENT_CALLS = 5

# Below this many calls in both spans a change means nothing ("+1 on last
# Tuesday"), so it is left out.
MIN_CALLS_FOR_CHANGE = 5


class DashboardRange(StrEnum):
    TODAY = "today"
    LAST_7_DAYS = "7d"
    LAST_30_DAYS = "30d"


@dataclass(frozen=True, slots=True)
class RangeBounds:
    start: datetime
    end: datetime
    # The span the change is measured against.
    previous_start: datetime
    previous_end: datetime


def range_bounds(range_: DashboardRange, tz: ZoneInfo, now: datetime) -> RangeBounds:
    """Today runs from local midnight to now and is compared with the same
    hours a week ago; 7 and 30 days end now, start at local midnight (so 7 days
    is today plus the six days before) and are compared with the span of the
    same length just before."""
    local_now = now.astimezone(tz)
    midnight = datetime.combine(local_now.date(), time.min, tzinfo=tz)
    if range_ == DashboardRange.TODAY:
        week = timedelta(days=7)
        return RangeBounds(midnight, now, midnight - week, now - week)
    days = 7 if range_ == DashboardRange.LAST_7_DAYS else 30
    start = datetime.combine(
        local_now.date() - timedelta(days=days - 1), time.min, tzinfo=tz
    )
    previous_start = datetime.combine(
        local_now.date() - timedelta(days=2 * days - 1), time.min, tzinfo=tz
    )
    return RangeBounds(start, now, previous_start, start)


def calls_by_hour(calls: Iterable[CallView], tz: ZoneInfo) -> list[int]:
    """Calls per local hour of the day (0-23), summed over the range."""
    hours = [0] * 24
    for call in calls:
        hours[call.created_at.astimezone(tz).hour] += 1
    return hours


def call_change(current: int, previous: int) -> int | None:
    """current - previous, or None when both are too small to compare."""
    if current < MIN_CALLS_FOR_CHANGE and previous < MIN_CALLS_FOR_CHANGE:
        return None
    return current - previous


def tiles(calls: Sequence[CallView]) -> dict[str, Any]:
    total = len(calls)
    counts: dict[CallResult, int] = {}
    for call in calls:
        counts[call.result] = counts.get(call.result, 0) + 1
    handled = sum(counts.get(result, 0) for result in HANDLED_RESULTS)
    picked_up = counts.get(CallResult.PASSED_TO_TEAM, 0)
    not_answered = counts.get(CallResult.TRANSFER_NOT_ANSWERED, 0)
    durations = [
        call.duration_seconds
        for call in calls
        if call.duration_seconds is not None
        and call.duration_seconds > 0
        and call.result != CallResult.IN_PROGRESS
    ]
    return {
        "calls": total,
        "handled": handled,
        "handled_percent": round(handled * 100 / total) if total else None,
        "passed_to_team": picked_up + not_answered,
        "transfer_picked_up": picked_up,
        "transfer_not_answered": not_answered,
        "hung_up_silent": counts.get(CallResult.HUNG_UP_SILENT, 0),
        "callbacks_requested": counts.get(CallResult.CALLBACK_REQUESTED, 0),
        "in_progress": counts.get(CallResult.IN_PROGRESS, 0),
        "average_call_seconds": (
            round(sum(durations) / len(durations)) if durations else None
        ),
    }


def recent_calls(calls: Sequence[CallView]) -> list[dict[str, Any]]:
    """The newest calls first (``calls`` is newest first)."""
    return [
        {
            "run_id": call.run_id,
            "workflow_id": call.workflow_id,
            "created_at": call.created_at,
            "caller_number": call.caller_number,
            "caller_name": call.caller_name,
            "result": call.result,
            "duration_seconds": call.duration_seconds,
            "has_recording": call.has_recording,
        }
        for call in calls[:RECENT_CALLS]
    ]


class NotAnsweringReason(StrEnum):
    # Spendable credit is under the minimum a call needs to start.
    NO_CREDIT = "no_credit"
    # No phone number is linked to the agent (or to any agent).
    NO_NUMBER = "no_number"
    # The linked number, or its phone account, is switched off.
    NUMBER_OFF = "number_off"
    # The agent the number rings is switched off (archived).
    AGENT_OFF = "agent_off"
    # There is no agent yet.
    NO_AGENT = "no_agent"


def agent_status(
    *,
    agents: Sequence[Mapping[str, Any]],
    numbers: Sequence[Mapping[str, Any]],
    workflow_id: int | None,
    credit_too_low: bool,
    last_call_at: datetime | None,
) -> dict[str, Any]:
    """Whether calls to the business are being answered, and if not, why.

    A carrier outage can't be seen from here, so ``last_call_at`` is returned
    as an honest hint next to the status.
    """
    scoped = [a for a in agents if workflow_id is None or a["id"] == workflow_id]
    active_ids = {a["id"] for a in scoped if a.get("status") == "active"}
    scoped_ids = {a["id"] for a in scoped}
    linked = [n for n in numbers if n.get("inbound_workflow_id") in scoped_ids]
    switched_on = [
        n for n in linked if n.get("is_active") and not n.get("config_inactive")
    ]
    live = [n for n in switched_on if n["inbound_workflow_id"] in active_ids]

    reason: NotAnsweringReason | None
    if not scoped:
        reason = NotAnsweringReason.NO_AGENT
    elif not linked:
        reason = NotAnsweringReason.NO_NUMBER
    elif not switched_on:
        reason = NotAnsweringReason.NUMBER_OFF
    elif not live:
        reason = NotAnsweringReason.AGENT_OFF
    elif credit_too_low:
        reason = NotAnsweringReason.NO_CREDIT
    else:
        reason = None
    shown = live or switched_on or linked
    return {
        "answering": reason is None,
        "reason": reason,
        "phone_numbers": [n["address"] for n in (live if reason is None else shown)],
        "last_call_at": last_call_at,
    }


def credit_summary(
    *,
    balance_eur: Decimal,
    credit_limit_eur: Decimal,
    rate_per_minute_eur: Decimal,
    min_balance_for_call_eur: Decimal,
    low_balance_warning_eur: Decimal,
) -> dict[str, Any]:
    """Credit left and about how many minutes of calls it pays for."""
    spendable = balance_eur + credit_limit_eur
    minutes = (
        int((spendable / rate_per_minute_eur).to_integral_value(rounding=ROUND_FLOOR))
        if rate_per_minute_eur > 0 and spendable > 0
        else (None if rate_per_minute_eur <= 0 else 0)
    )
    return {
        "balance_eur": balance_eur,
        "spendable_eur": spendable,
        "rate_per_minute_eur": rate_per_minute_eur,
        "minutes_left": minutes,
        "too_low": spendable < min_balance_for_call_eur,
        "running_low": spendable < low_balance_warning_eur,
    }
