"""Home's numbers, counted from stored calls. Pure functions; the loader in
``service.py`` does the reading."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from api.schemas.opening_hours import OpeningHours
from api.services.dashboard.calls import HANDLED_RESULTS, CallResult, CallView
from api.services.workflow.opening_hours import (
    describe_opening_hours,
    is_after_hours,
    minute_ranges,
    open_minutes,
    parse_opening_hours,
)

RECENT_CALLS = 5
# After-hours calls listed under the count, newest first.
AFTER_HOURS_LISTED = 5

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


def _hours_by_agent(agents: Sequence[Mapping[str, Any]]) -> dict[int, OpeningHours]:
    return {
        a["id"]: parsed
        for a in agents
        if (parsed := parse_opening_hours(a.get("opening_hours_schedule")))
    }


def _shown_agents(
    calls: Sequence[CallView], agents: Sequence[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    """The agents Home speaks for: switched on, or with calls in the range."""
    with_calls = {call.workflow_id for call in calls}
    return [a for a in agents if a.get("status") == "active" or a["id"] in with_calls]


def after_hours(
    calls: Sequence[CallView], agents: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Calls that arrived while their agent's business was closed, by each
    agent's structured opening hours (``get_dashboard_agents``). Agents
    without them aren't counted and are listed (those that are switched on
    or had calls), so the screen can say so; ``calls`` is None when none of
    the agents has them. ``recent`` is the newest few of those calls
    (``calls`` is newest first), so the owner can see who rang and when."""
    hours = _hours_by_agent(agents)
    closed = [
        call
        for call in calls
        if is_after_hours(call.workflow_id, call.created_at, hours)
    ]
    return {
        "calls": len(closed) if hours else None,
        "agents_without_hours": [
            {"id": a["id"], "name": a["name"]}
            for a in _shown_agents(calls, agents)
            if a["id"] not in hours
        ],
        "recent": [
            {
                "run_id": call.run_id,
                "workflow_id": call.workflow_id,
                "created_at": call.created_at,
                "caller_number": call.caller_number,
                "caller_name": call.caller_name,
                "result": call.result,
            }
            for call in closed[:AFTER_HOURS_LISTED]
        ],
    }


class OpeningHoursBand(StrEnum):
    """What the calls-per-hour chart can shade as open."""

    # None of the agents shown has opening hours set as times.
    NONE = "none"
    # The agents shown have different hours: no one band is true for all.
    DIFFER = "differ"
    # The same open times on every day of the range (always so for Today);
    # no ranges means closed all of it.
    SAME = "same"
    # The days differ: the band is the times open on more than half of the
    # range's days (none when no time is).
    MOST_DAYS = "most_days"


def _range_days(start: datetime, end: datetime, tz: ZoneInfo) -> list[date]:
    first = start.astimezone(tz).date()
    last = end.astimezone(tz).date()
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def opening_hours_band(
    calls: Sequence[CallView],
    agents: Sequence[Mapping[str, Any]],
    tz: ZoneInfo,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """The open times to shade behind the calls-per-hour chart, as wall-clock
    minute ranges in *tz* (Home's zone), for the agents shown.

    Only when every agent shown that has hours set as times has the same
    ones: else ``differ``. Over one day (Today) the band is that day's
    hours. Over 7 or 30 days the chart sums every day, so the band is the
    hours when they are the same each day (``same``); when the days differ
    it is the times open on more than half of the days (``most_days``), and
    ``days_open`` / ``days`` and the hours in words let the screen say so
    plainly. Agents without hours as times are left out (``none`` when that
    is all of them)."""
    shown = _shown_agents(calls, agents) or list(agents)
    hours = _hours_by_agent(shown)
    days = _range_days(start, end, tz)
    blank: dict[str, Any] = {
        "kind": OpeningHoursBand.NONE,
        "ranges": [],
        "days": len(days),
        "days_open": 0,
        "description": None,
    }
    if not hours:
        return blank
    distinct = {(h.days, h.timezone) for h in hours.values()}
    if len(distinct) > 1:
        return {**blank, "kind": OpeningHoursBand.DIFFER}
    shared = next(iter(hours.values()))
    per_day = [open_minutes(shared, day, tz) for day in days]
    if all(minutes == per_day[0] for minutes in per_day):
        kind, band = OpeningHoursBand.SAME, per_day[0]
    else:
        kind = OpeningHoursBand.MOST_DAYS
        band = [
            sum(minutes[m] for minutes in per_day) * 2 > len(per_day)
            for m in range(len(per_day[0]))
        ]
    return {
        "kind": kind,
        "ranges": [{"start": a, "end": b} for a, b in minute_ranges(band)],
        "days": len(days),
        "days_open": sum(1 for minutes in per_day if any(minutes)),
        # The times only: the owner's note is said by the agent, not drawn.
        "description": describe_opening_hours(shared.model_copy(update={"note": None})),
    }


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
        # Calls with no conversation: silent, hung up at once, never connected
        # or dropped. With handled, callbacks, passed to team and in progress
        # this accounts for every call, so the tiles add up to the total.
        "no_conversation": sum(
            counts.get(result, 0)
            for result in (
                CallResult.HUNG_UP_SILENT,
                CallResult.HUNG_UP_EARLY,
                CallResult.NOT_CONNECTED,
                CallResult.CALL_DROPPED,
            )
        ),
        "callbacks_requested": counts.get(CallResult.CALLBACK_REQUESTED, 0),
        "in_progress": counts.get(CallResult.IN_PROGRESS, 0),
        # Bookings the calendar confirmed on the call.
        "bookings_taken": counts.get(CallResult.BOOKING_MADE, 0),
        # Every line was busy and nobody on the team took the call.
        "lines_busy": counts.get(CallResult.LINES_BUSY, 0),
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
            "summary": _review_text(call, "summary"),
            "reason_label": _review_text(call, "reason_label"),
        }
        for call in calls[:RECENT_CALLS]
    ]


def _review_text(call: CallView, key: str) -> str | None:
    value = (call.review or {}).get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


NOT_REVIEWED = "not_reviewed"
NOT_REVIEWED_LABEL = "Not reviewed yet"
# Calls no review is ever written for: nobody was on the line yet, the call
# never connected, or every line was busy (the agent never took it).
_NEVER_REVIEWED = frozenset(
    {CallResult.IN_PROGRESS, CallResult.NOT_CONNECTED, CallResult.LINES_BUSY}
)


def turned_away_today(
    calls: Iterable[CallView], tz: ZoneInfo, now: datetime
) -> dict[str, int]:
    """Today's callers who rang while every line was busy (the business's
    calls-at-once limit), and what came of them. Every range Home shows
    ends now and includes today, so today's calls are always loaded."""
    midnight = datetime.combine(now.astimezone(tz).date(), time.min, tzinfo=tz)
    today = [c for c in calls if c.lines_busy and c.created_at >= midnight]
    return {
        "calls": len(today),
        "forwarded": sum(1 for c in today if c.lines_busy == "forwarded"),
        "voicemails": sum(1 for c in today if c.lines_busy == "voicemail"),
    }


def _percents(counts: Sequence[int]) -> list[int]:
    """Each count's whole percent of the total. Rounded on their own, so
    equal counts always show the same percent (the sum may be 99 or 101)."""
    total = sum(counts)
    return [round(c * 100 / total) if total else 0 for c in counts]


def callers_wanted(calls: Iterable[CallView]) -> list[dict[str, Any]]:
    """What callers wanted, from each call's review: one row per reason
    with its count and percent, most common first, "Other" and then "Not
    reviewed yet" (calls whose review hasn't been written) last. A reason's
    label is the one its reviews were written with."""
    counts: dict[str, int] = {}
    labels: dict[str, dict[str, int]] = {}
    for call in calls:
        reason = (call.review or {}).get("reason")
        if isinstance(reason, str) and reason:
            label = _review_text(call, "reason_label") or reason.replace("_", " ")
            counts[reason] = counts.get(reason, 0) + 1
            seen = labels.setdefault(reason, {})
            seen[label] = seen.get(label, 0) + 1
        elif call.result not in _NEVER_REVIEWED and not call.lines_busy:
            counts[NOT_REVIEWED] = counts.get(NOT_REVIEWED, 0) + 1
            labels[NOT_REVIEWED] = {NOT_REVIEWED_LABEL: 1}

    def label(key: str) -> str:
        seen = labels[key]
        return max(seen, key=lambda name: (seen[name], name))

    def order(key: str) -> tuple[int, int, str]:
        last = 2 if key == NOT_REVIEWED else 1 if key == "other" else 0
        return (last, -counts[key], label(key))

    keys = sorted(counts, key=order)
    percents = _percents([counts[k] for k in keys])
    return [
        {"key": k, "label": label(k), "count": counts[k], "percent": p}
        for k, p in zip(keys, percents)
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
