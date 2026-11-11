"""Every report card's numbers, counted from stored calls. Pure functions;
``service.py`` does the reading.

Each call is read the way Home and Calls read it (``dashboard.calls
.call_result``), so a "booking made" or "passed to your team" here is the
same call there. The rest comes from what the agent wrote down on the call
(``gathered_context``) and from the call review (``annotations
.call_review``). Nothing is estimated except the money cards, which only
exist once the owner gives their own average.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from api.schemas.opening_hours import OpeningHours
from api.services.call_review.categories import OTHER, ReasonSet
from api.services.call_review.review import request_tags
from api.services.calls.lines_busy import PLAN_KEY, LinesBusyOutcome, was_forwarded
from api.services.dashboard.calls import (
    HANDLED_RESULTS,
    UNREACHED_RESULTS,
    CallResult,
    CallView,
    number_key,
)
from api.services.dashboard.follow_ups import (
    FollowUp,
    FollowUpKind,
    follow_ups,
    unanswered_questions,
)
from api.services.dashboard.summary import (
    NOT_REVIEWED,
    NOT_REVIEWED_LABEL,
    call_change,
)
from api.services.report_cards import fields
from api.services.report_cards.catalogue import Card, PackSpec
from api.services.workflow.opening_hours import is_open

# The calls that needed someone from the business.
NEEDED_PERSON = frozenset(
    {
        CallResult.PASSED_TO_TEAM,
        CallResult.TRANSFER_NOT_ANSWERED,
        CallResult.CALLBACK_REQUESTED,
    }
)
# Never reviewed: nobody was on the line yet, or the call never connected.
_NEVER_REVIEWED = frozenset({CallResult.IN_PROGRESS, CallResult.NOT_CONNECTED})
# Follow-ups that are a person waiting to be rung back.
CALLBACK_KINDS = frozenset(
    {
        FollowUpKind.CALLBACK,
        FollowUpKind.TRANSFER_NOT_ANSWERED,
        FollowUpKind.REPEAT_CALLER,
    }
)

MAX_QUESTIONS = 8
MAX_LIST = 6
MAX_AREAS = 8
FILLING_DAYS = 14

# Busiest times: a two-hour slot is worth a tip only when it clearly stands
# out: enough calls to mean something, a real share of them, and well ahead
# of the next busiest slot.
TIP_MIN_CALLS = 20
TIP_MIN_SLOT_CALLS = 5
TIP_MIN_SHARE = 0.10
TIP_LEAD = 1.5

# Call spikes: an hour with at least this many calls and this many times
# its usual number (the same hour's average over the period's days).
SPIKE_MIN_CALLS = 4
SPIKE_FACTOR = 3


@dataclass(frozen=True, slots=True)
class ReportCall:
    view: CallView
    # What the agent wrote down on the call.
    gathered: Mapping[str, Any] = field(default_factory=dict)

    @property
    def result(self) -> CallResult:
        return self.view.result

    @property
    def reason(self) -> str | None:
        value = (self.view.review or {}).get("reason")
        return value if isinstance(value, str) and value else None

    def detail(self, key: str) -> str | None:
        return fields.text(self.gathered, key)


@dataclass(frozen=True, slots=True)
class Span:
    """The period a report covers and what it is compared with."""

    start: datetime
    end: datetime
    previous_start: datetime
    previous_end: datetime
    tz: ZoneInfo
    now: datetime
    # Opening hours set as times, by agent id. Agents without are missing.
    hours: Mapping[int, OpeningHours] = field(default_factory=dict)
    # Agents whose calls can't be checked against opening hours.
    agents_without_hours: Sequence[str] = ()

    @property
    def first_day(self) -> date:
        return self.start.astimezone(self.tz).date()

    @property
    def last_day(self) -> date:
        return (self.end - timedelta(microseconds=1)).astimezone(self.tz).date()

    @property
    def days(self) -> int:
        return (self.last_day - self.first_day).days + 1


def _count(calls: Iterable[ReportCall], test: Callable[[ReportCall], bool]) -> int:
    return sum(1 for call in calls if test(call))


def _results(calls: Iterable[ReportCall]) -> Counter[CallResult]:
    return Counter(call.result for call in calls)


def _change(current: int, previous: int) -> dict[str, Any]:
    return {
        "previous": previous,
        "change": call_change(current, previous),
    }


def _percent(part: int, whole: int) -> int | None:
    return round(part * 100 / whole) if whole else None


def _closed(call: ReportCall, span: Span) -> bool:
    hours = span.hours.get(call.view.workflow_id)
    return hours is not None and not is_open(hours, call.view.created_at)


def _local(call: ReportCall, span: Span) -> datetime:
    return call.view.created_at.astimezone(span.tz)


# --------------------------------------------------------------- shared


def calls_answered(
    calls: Sequence[ReportCall], previous: Sequence[ReportCall], span: Span
) -> dict[str, Any]:
    """Every inbound call in the period (Home's "Calls"), and how many came
    in while the business was closed (None when no agent has its opening
    hours set as times)."""
    return {
        "calls": len(calls),
        **_change(len(calls), len(previous)),
        "after_hours": _count(calls, lambda c: _closed(c, span))
        if span.hours
        else None,
    }


def _series(
    calls: Sequence[ReportCall], reasons: ReasonSet
) -> tuple[list[dict[str, Any]], Callable[[ReportCall], str | None]]:
    """The reasons that occur, in the template's fixed order (its own
    reasons, any older ones, Other, Not reviewed yet), and the key each
    call counts under (None: never reviewed, left out)."""

    def key(call: ReportCall) -> str | None:
        if call.reason:
            return call.reason
        return None if call.result in _NEVER_REVIEWED else NOT_REVIEWED

    counts: Counter[str] = Counter()
    labels: dict[str, str] = {}
    for call in calls:
        k = key(call)
        if k is None:
            continue
        counts[k] += 1
        if k not in labels:
            stored = (call.view.review or {}).get("reason_label")
            labels[k] = stored if isinstance(stored, str) and stored else k

    def order(k: str) -> tuple[int, int, str]:
        if k == NOT_REVIEWED:
            return (3, 0, "")
        if k == OTHER:
            return (2, 0, "")
        if k in reasons.keys:
            return (0, reasons.keys.index(k), "")
        return (1, 0, labels[k])

    series = [
        {
            "key": k,
            "label": NOT_REVIEWED_LABEL
            if k == NOT_REVIEWED
            else reasons.label(k)
            if k in reasons.keys
            else labels[k],
            "count": counts[k],
        }
        for k in sorted(counts, key=order)
    ]
    return series, key


def callers_wanted(
    calls: Sequence[ReportCall], reasons: ReasonSet, span: Span
) -> dict[str, Any]:
    """Calls per day (per hour on a one-day report) by the call review's
    reason. Calls still on the line or that never connected have no review
    and are left out; reviews not written yet show as "Not reviewed yet"."""
    series, key = _series(calls, reasons)
    hourly = span.days == 1
    buckets: dict[Any, Counter[str]] = {}
    if hourly:
        hours = [_local(c, span).hour for c in calls]
        first, last = min([8, *hours]), max([20, *hours])
        for hour in range(first, last + 1):
            buckets[hour] = Counter()
    else:
        day = span.first_day
        while day <= span.last_day:
            buckets[day] = Counter()
            day += timedelta(days=1)
    for call in calls:
        k = key(call)
        if k is None:
            continue
        local = _local(call, span)
        slot = local.hour if hourly else local.date()
        if slot in buckets:
            buckets[slot][k] += 1
    return {
        "unit": "hour" if hourly else "day",
        "series": series,
        "buckets": [
            {
                "date": None if hourly else slot,
                "hour": slot if hourly else None,
                "counts": dict(counts),
                "total": sum(counts.values()),
            }
            for slot, counts in buckets.items()
        ],
    }


def busiest_times(calls: Sequence[ReportCall], span: Span) -> dict[str, Any]:
    """Calls by weekday (Monday first) and local hour, and a tip naming a
    two-hour slot only when it clearly stands out (see ``TIP_*``)."""
    grid = [[0] * 24 for _ in range(7)]
    for call in calls:
        local = _local(call, span)
        grid[local.weekday()][local.hour] += 1
    total = len(calls)
    busy = [h for h in range(24) if any(grid[d][h] for d in range(7))]
    first, last = min([9, *busy]), max([17, *busy])
    return {
        "grid": grid,
        "first_hour": first,
        "last_hour": last,
        "max": max((max(row) for row in grid), default=0),
        "calls": total,
        "tip": _busiest_tip(grid, total),
    }


def _busiest_tip(grid: list[list[int]], total: int) -> dict[str, Any] | None:
    if total < TIP_MIN_CALLS:
        return None
    slots = [(grid[d][h] + grid[d][h + 1], d, h) for d in range(7) for h in range(23)]
    # Ties go to the slot that starts at the busier hour, then the earliest.
    best, day, hour = max(slots, key=lambda s: (s[0], grid[s[1]][s[2]], -s[1], -s[2]))
    runner_up = max(
        (s[0] for s in slots if s[1] != day or abs(s[2] - hour) >= 2), default=0
    )
    if (
        best < TIP_MIN_SLOT_CALLS
        or best / total < TIP_MIN_SHARE
        or best < TIP_LEAD * runner_up
    ):
        return None
    return {
        "weekday": day,
        "start_hour": hour,
        "end_hour": hour + 2,
        "calls": best,
        "one_in": max(1, round(total / best)),
    }


def unanswered(calls: Sequence[ReportCall]) -> dict[str, Any]:
    """The questions the call review found the agent couldn't answer,
    grouped by wording (case and punctuation aside), most asked first. Each
    group points at its latest call, which "Add an answer" marks done."""
    groups: dict[str, dict[str, Any]] = {}
    asked = 0
    for call in sorted(calls, key=lambda c: c.view.created_at, reverse=True):
        questions = unanswered_questions(call.view)
        if not questions:
            continue
        asked += 1
        done = "unanswered_question" in (call.view.follow_up_marks or {})
        for question in {fields.question_key(q): q for q in questions}.items():
            key, words = question
            group = groups.get(key)
            if group is None:
                groups[key] = {
                    "question": words,
                    "count": 1,
                    "run_id": call.view.run_id,
                    "workflow_id": call.view.workflow_id,
                    "last_asked_at": call.view.created_at,
                    "answered": done,
                }
            else:
                group["count"] += 1
    ranked = sorted(
        groups.values(), key=lambda g: (-g["count"], -g["last_asked_at"].timestamp())
    )
    return {
        "calls": asked,
        "groups": ranked[:MAX_QUESTIONS],
        "more": max(0, len(ranked) - MAX_QUESTIONS),
    }


def _wait_minutes(item: FollowUp) -> float | None:
    done = item.done_at
    if done is None or done < item.call.created_at:
        return None
    return (done - item.call.created_at).total_seconds() / 60


def follow_up_stats(calls: Sequence[ReportCall]) -> dict[str, Any]:
    """The follow-ups the period's calls raised (Follow-ups' own rules),
    how many are sorted, the usual (median) wait from the call to someone
    marking it done, and how many of each kind."""
    items = follow_ups(c.view for c in calls)
    waits = [w for w in (_wait_minutes(i) for i in items if i.done) if w is not None]
    kinds = Counter(i.kind for i in items)
    return {
        "raised": len(items),
        "sorted": sum(1 for i in items if i.done),
        "open": sum(1 for i in items if not i.done),
        "median_wait_minutes": round(median(waits)) if waits else None,
        "kinds": [
            {"kind": kind, "count": kinds[kind]} for kind in FollowUpKind if kinds[kind]
        ],
    }


def after_hours(calls: Sequence[ReportCall], span: Span) -> dict[str, Any]:
    """Calls that came in while the business was closed, by each agent's
    opening hours set as times, and what came of them."""
    if not span.hours:
        return {
            "hours_set": False,
            "calls": None,
            "bookings": None,
            "callbacks": None,
            "handled": None,
            "agents_without_hours": list(span.agents_without_hours),
        }
    closed = [c for c in calls if _closed(c, span)]
    results = _results(closed)
    return {
        "hours_set": True,
        "calls": len(closed),
        "bookings": results[CallResult.BOOKING_MADE],
        "callbacks": results[CallResult.CALLBACK_REQUESTED],
        "handled": sum(results[r] for r in HANDLED_RESULTS),
        "agents_without_hours": list(span.agents_without_hours),
    }


MAX_BUSY_SLOTS = 3


def lines_busy(calls: Sequence[ReportCall], span: Span) -> dict[str, Any]:
    """Callers who rang while every line was busy (the calls-at-once
    limit): how many, how many were put through to the team or left a
    voicemail, and the hours it happened most (weekday and local hour)."""
    busy = [c for c in calls if c.view.lines_busy]
    outcomes = Counter(c.view.lines_busy for c in busy)
    slots: Counter[tuple[int, int]] = Counter()
    for call in busy:
        local = _local(call, span)
        slots[(local.weekday(), local.hour)] += 1
    ranked = sorted(slots.items(), key=lambda s: (-s[1], s[0]))
    limit = None
    for call in sorted(busy, key=lambda c: c.view.created_at, reverse=True):
        value = (call.gathered.get(PLAN_KEY) or {}).get("limit")
        if isinstance(value, int) and not isinstance(value, bool):
            limit = value
            break
    return {
        "calls": len(busy),
        # Rang the team's phone, and of those, someone picked up.
        "forwarded": sum(1 for c in busy if was_forwarded(c.gathered)),
        "answered": outcomes[LinesBusyOutcome.FORWARDED.value],
        "voicemails": outcomes[LinesBusyOutcome.VOICEMAIL.value],
        "no_message": outcomes[LinesBusyOutcome.NO_MESSAGE.value],
        "told_busy": outcomes[LinesBusyOutcome.TOLD_BUSY.value],
        "busiest": [
            {"weekday": day, "hour": hour, "calls": count}
            for (day, hour), count in ranked[:MAX_BUSY_SLOTS]
        ],
        "limit": limit,
    }


def agent_performance(calls: Sequence[ReportCall]) -> dict[str, Any]:
    """Home's own split: handled start to finish (``HANDLED_RESULTS``),
    needed a person, and calls with no conversation."""
    results = _results(calls)
    handled = sum(results[r] for r in HANDLED_RESULTS)
    return {
        "calls": len(calls),
        "handled": handled,
        "handled_percent": _percent(handled, len(calls)),
        "needed_person": sum(results[r] for r in NEEDED_PERSON),
        "passed_to_team": results[CallResult.PASSED_TO_TEAM]
        + results[CallResult.TRANSFER_NOT_ANSWERED],
        "callbacks": results[CallResult.CALLBACK_REQUESTED],
        "no_conversation": sum(results[r] for r in UNREACHED_RESULTS),
        "hung_up_silent": results[CallResult.HUNG_UP_SILENT],
        "in_progress": results[CallResult.IN_PROGRESS],
        "results": {r.value: results[r] for r in CallResult if results[r]},
    }


# ---------------------------------------------------------- bookings


def _booked(calls: Iterable[ReportCall]) -> list[ReportCall]:
    return [c for c in calls if c.result == CallResult.BOOKING_MADE]


def bookings(
    calls: Sequence[ReportCall], previous: Sequence[ReportCall]
) -> dict[str, Any]:
    """Bookings the calendar confirmed on the call (Home's "bookings
    taken"), and their share of the period's calls."""
    count = len(_booked(calls))
    return {
        "count": count,
        **_change(count, len(_booked(previous))),
        "percent_of_calls": _percent(count, len(calls)),
    }


@dataclass(frozen=True, slots=True)
class Sizes:
    covers: int
    with_size: int
    not_given: int
    unreadable: int


def _sizes(calls: Iterable[ReportCall]) -> Sizes:
    covers = with_size = not_given = unreadable = 0
    for call in calls:
        raw = call.gathered.get("party_size")
        size = fields.party_size(raw)
        if size is not None:
            covers += size
            with_size += 1
        elif fields.text(call.gathered, "party_size") is None:
            not_given += 1
        else:
            unreadable += 1
    return Sizes(covers, with_size, not_given, unreadable)


def covers(
    calls: Sequence[ReportCall], previous: Sequence[ReportCall]
) -> dict[str, Any]:
    """People booked for: the party size the agent wrote down on each call
    where a booking was made. Bookings without a size, or with one that
    can't be read for sure ("4 or 5"), are counted apart, not guessed."""
    now, before = _sizes(_booked(calls)), _sizes(_booked(previous))
    return {
        "covers": now.covers,
        **_change(now.covers, before.covers),
        "bookings_with_size": now.with_size,
        "not_given": now.not_given,
        "unreadable": now.unreadable,
        "average_party": round(now.covers / now.with_size, 1)
        if now.with_size
        else None,
    }


def _time_was_full(call: ReportCall) -> bool:
    # As Follow-ups raises it: the review says so and no booking was made.
    return (call.view.review or {}).get(
        "time_was_full"
    ) is True and call.result != CallResult.BOOKING_MADE


def tables_full(
    calls: Sequence[ReportCall], previous: Sequence[ReportCall], span: Span
) -> dict[str, Any]:
    """Callers who wanted a time that was full and didn't book: how many,
    for how many people, and the days and hour they mostly wanted."""
    full = [c for c in calls if _time_was_full(c)]
    sizes = _sizes(full)
    days: Counter[int] = Counter()
    hours: Counter[int] = Counter()
    for call in full:
        day = fields.booking_day(call.gathered.get("booking_date"))
        if day is not None:
            days[day.weekday()] += 1
        clock = fields.booking_clock(call.gathered.get("booking_time"))
        if clock is not None:
            hours[clock.hour] += 1
    return {
        "count": len(full),
        **_change(len(full), sum(1 for c in previous if _time_was_full(c))),
        "covers": sizes.covers,
        "without_size": sizes.not_given + sizes.unreadable,
        "mostly_days": _mostly(days),
        "mostly_hour": _mostly_one(hours),
    }


def _mostly(counts: Counter[int], *, at_most: int = 2) -> list[int]:
    """The one or two values that make up most (60%+) of at least 3."""
    total = sum(counts.values())
    if total < 3:
        return []
    picked: list[int] = []
    share = 0
    for value, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        picked.append(value)
        share += n
        if share / total >= 0.6:
            return sorted(picked)
        if len(picked) == at_most:
            break
    return []


def _mostly_one(counts: Counter[int]) -> int | None:
    total = sum(counts.values())
    if total < 3:
        return None
    value, n = max(counts.items(), key=lambda kv: (kv[1], -kv[0]))
    return value if n / total >= 0.4 else None


def days_filling(calls: Sequence[ReportCall], span: Span) -> dict[str, Any]:
    """The people booked by phone in this period, by the day the booking is
    for, over the next two weeks from today. A day is closed when every
    agent with opening hours set as times is closed all of it."""
    today = span.now.astimezone(span.tz).date()
    window = [today + timedelta(days=i) for i in range(FILLING_DAYS)]
    per_day: dict[date, list[int]] = {d: [0, 0] for d in window}
    without_day = later = without_size = 0
    for call in _booked(calls):
        day = fields.booking_day(call.gathered.get("booking_date"))
        if day is None:
            without_day += 1
            continue
        if day not in per_day:
            later += day > window[-1]
            continue
        size = fields.party_size(call.gathered.get("party_size"))
        per_day[day][1] += 1
        if size is None:
            without_size += 1
        else:
            per_day[day][0] += size
    hours = list(span.hours.values())
    return {
        "days": [
            {
                "date": day,
                "covers": covers_,
                "bookings": count,
                "closed": bool(hours) and all(not h.days[day.weekday()] for h in hours),
            }
            for day, (covers_, count) in per_day.items()
        ],
        "without_size": without_size,
        "without_day": without_day,
        "later": later,
    }


def special_requests(
    calls: Sequence[ReportCall], reasons: ReasonSet
) -> dict[str, Any] | None:
    """What callers asked for with their booking, from the call review's
    request tags. Calls reviewed before tags existed aren't counted as "no
    request": those whose details mention a request are reported apart."""
    if not reasons.request_tags:
        return None
    counts: Counter[str] = Counter()
    tagged = with_requests = not_tagged = 0
    for call in calls:
        tags = request_tags(call.view.review)
        if tags is None:
            if call.detail("special_requests"):
                not_tagged += 1
            continue
        tagged += 1
        known = [t for t in tags if t in reasons.request_tag_keys]
        with_requests += bool(known)
        counts.update(set(known))
    order = {key: i for i, key in enumerate(reasons.request_tag_keys)}
    return {
        "tags": [
            {"key": t.key, "label": t.label, "count": counts[t.key]}
            for t in sorted(
                reasons.request_tags, key=lambda t: (-counts[t.key], order[t.key])
            )
            if counts[t.key]
        ],
        "calls_with_requests": with_requests,
        "tagged_calls": tagged,
        "not_tagged": not_tagged,
    }


def _reason_card(
    calls: Sequence[ReportCall],
    previous: Sequence[ReportCall],
    reason: str,
    span: Span,
) -> dict[str, Any]:
    """Calls the review put under one reason, and what came of them."""
    mine = [c for c in calls if c.reason == reason]
    results = _results(mine)
    return {
        "count": len(mine),
        **_change(len(mine), sum(1 for c in previous if c.reason == reason)),
        "handled": sum(results[r] for r in HANDLED_RESULTS),
        "booked": results[CallResult.BOOKING_MADE],
        "passed_to_team": results[CallResult.PASSED_TO_TEAM]
        + results[CallResult.TRANSFER_NOT_ANSWERED],
        "callbacks": results[CallResult.CALLBACK_REQUESTED],
        "needed_person": sum(results[r] for r in NEEDED_PERSON),
        "after_hours": _count(mine, lambda c: _closed(c, span)) if span.hours else None,
    }


# ------------------------------------------------------------- clinic


def patient_status(calls: Sequence[ReportCall]) -> dict[str, Any]:
    """New and existing patients, as the agent wrote them down."""
    counts: Counter[str] = Counter()
    not_said = 0
    for call in calls:
        value = (call.detail("patient_status") or "").lower()
        if not value:
            not_said += call.result == CallResult.BOOKING_MADE
            continue
        if "new" in value:
            counts["new"] += 1
        elif any(w in value for w in ("exist", "return", "current", "regular")):
            counts["existing"] += 1
        else:
            counts["other"] += 1
    return {
        "new": counts["new"],
        "existing": counts["existing"],
        "other": counts["other"],
        "booked_not_said": not_said,
    }


def appointment_types(calls: Sequence[ReportCall]) -> dict[str, Any]:
    """The kind of appointment each caller wanted, as the agent wrote it,
    and how many of those calls booked."""
    asked: Counter[str] = Counter()
    booked: Counter[str] = Counter()
    labels: dict[str, str] = {}
    for call in calls:
        value = call.detail("appointment_type")
        if not value:
            continue
        key = " ".join(value.lower().split())
        labels.setdefault(key, value[:1].upper() + value[1:])
        asked[key] += 1
        booked[key] += call.result == CallResult.BOOKING_MADE
    ranked = sorted(asked, key=lambda k: (-asked[k], k))
    return {
        "types": [
            {"label": labels[k], "calls": asked[k], "booked": booked[k]}
            for k in ranked[:MAX_LIST]
        ],
        "other_calls": sum(asked[k] for k in ranked[MAX_LIST:]),
    }


# -------------------------------------------------------------- retail

# What the call review files each retail card's calls under.
RETAIL_REASON_CARDS = {
    Card.PRODUCT_ENQUIRIES: "product_stock",
    Card.ORDERS_DELIVERY: "orders_delivery",
    Card.RETURNS: "returns_faults",
    Card.SERVICING_REQUESTS: "servicing",
}


def top_products(calls: Sequence[ReportCall]) -> dict[str, Any]:
    """The products callers asked about, as the agent wrote them down
    (``product_asked_about``; several on one call separated by commas or
    semicolons), most asked first."""
    asked: Counter[str] = Counter()
    labels: dict[str, str] = {}
    with_product = 0
    for call in calls:
        value = call.detail("product_asked_about")
        if not value:
            continue
        with_product += 1
        names = {
            " ".join(part.lower().split()): part.strip()
            for part in value.replace(";", ",").split(",")
            if part.strip()
        }
        for key, words in names.items():
            labels.setdefault(key, words[:1].upper() + words[1:])
            asked[key] += 1
    ranked = sorted(asked, key=lambda k: (-asked[k], k))
    return {
        "products": [
            {"label": labels[k], "calls": asked[k]} for k in ranked[:MAX_LIST]
        ],
        "other_products": sum(asked[k] for k in ranked[MAX_LIST:]),
        "calls_with_product": with_product,
    }


# ------------------------------------------------------------- trades


def emergencies_by_hour(calls: Sequence[ReportCall], span: Span) -> dict[str, Any]:
    """Calls the agent marked as an emergency (``urgency``), by local hour."""
    hours = [0] * 24
    emergency = [c for c in calls if fields.is_emergency(c.gathered.get("urgency"))]
    for call in emergency:
        hours[_local(call, span).hour] += 1
    peak = max(range(24), key=lambda h: (hours[h], -h))
    return {
        "hours": hours,
        "count": len(emergency),
        "after_hours": _count(emergency, lambda c: _closed(c, span))
        if span.hours
        else None,
        "peak_hour": peak if len(emergency) >= 3 and hours[peak] >= 2 else None,
    }


def areas(calls: Sequence[ReportCall]) -> dict[str, Any]:
    """Where jobs are, from the address the agent wrote down: its town, or
    its county when that's all there is. Addresses that can't be placed
    are counted apart."""
    counts: Counter[str] = Counter()
    unclear = 0
    for call in calls:
        place = fields.area(call.gathered.get("job_address"))
        if place is None:
            continue
        if place == fields.UNCLEAR:
            unclear += 1
        else:
            counts[place] += 1
    ranked = sorted(counts, key=lambda k: (-counts[k], k))
    return {
        "areas": [{"label": k, "count": counts[k]} for k in ranked[:MAX_AREAS]],
        "other_areas": sum(counts[k] for k in ranked[MAX_AREAS:]),
        "places": len(counts),
        "unclear": unclear,
        "with_address": sum(counts.values()) + unclear,
    }


def waiting(calls: Sequence[ReportCall], span: Span) -> dict[str, Any]:
    """People from this period still waiting to be rung back: open
    follow-ups that are a callback, a transfer nobody answered or a caller
    who rang more than once, oldest first."""
    by_run = {c.view.run_id: c for c in calls}
    items = [
        i
        for i in follow_ups(c.view for c in calls)
        if i.kind in CALLBACK_KINDS and not i.done
    ]
    items.sort(key=lambda i: i.call.created_at)
    return {
        "count": len(items),
        "oldest_minutes": round(
            (span.now - items[0].call.created_at).total_seconds() / 60
        )
        if items
        else None,
        "items": [
            {
                "run_id": i.call.run_id,
                "kind": i.kind,
                "caller_name": i.call.caller_name,
                "caller_number": i.call.callback_number or i.call.caller_number,
                "about": i.call.call_reason,
                "area": _area_or_none(by_run[i.call.run_id]),
                "created_at": i.call.created_at,
            }
            for i in items[:MAX_LIST]
        ],
    }


def _area_or_none(call: ReportCall) -> str | None:
    place = fields.area(call.gathered.get("job_address"))
    return None if place in (None, fields.UNCLEAR) else place


def after_hours_callouts(
    calls: Sequence[ReportCall], previous: Sequence[ReportCall], span: Span
) -> dict[str, Any]:
    """Urgent jobs (an emergency, or the review's "urgent" reason) that
    came in while closed."""

    def urgent(call: ReportCall) -> bool:
        return call.reason == "urgent" or fields.is_emergency(
            call.gathered.get("urgency")
        )

    if not span.hours:
        return {"hours_set": False, "count": None, "previous": 0, "change": None}
    mine = [c for c in calls if urgent(c) and _closed(c, span)]
    before = sum(1 for c in previous if urgent(c) and _closed(c, span))
    results = _results(mine)
    return {
        "hours_set": True,
        "count": len(mine),
        **_change(len(mine), before),
        "passed_to_team": results[CallResult.PASSED_TO_TEAM]
        + results[CallResult.TRANSFER_NOT_ANSWERED],
        "callbacks": results[CallResult.CALLBACK_REQUESTED],
    }


# --------------------------------------------------------------- voip


def sorted_split(
    calls: Sequence[ReportCall], previous: Sequence[ReportCall]
) -> dict[str, Any]:
    """Calls the agent sorted start to finish against those passed to a
    person (Home's own split)."""
    now, before = _results(calls), _results(previous)
    handled = sum(now[r] for r in HANDLED_RESULTS)
    needed = sum(now[r] for r in NEEDED_PERSON)
    return {
        "sorted": {
            "count": handled,
            "percent": _percent(handled, len(calls)),
            **_change(handled, sum(before[r] for r in HANDLED_RESULTS)),
        },
        "passed_on": {
            "count": needed,
            "percent": _percent(needed, len(calls)),
            **_change(needed, sum(before[r] for r in NEEDED_PERSON)),
        },
    }


def issues_by_type(calls: Sequence[ReportCall], reasons: ReasonSet) -> dict[str, Any]:
    """Each review reason, split into sorted by the agent, passed on to a
    person, and no conversation."""
    series, key = _series(calls, reasons)
    rows = []
    for item in series:
        mine = [c for c in calls if key(c) == item["key"]]
        results = _results(mine)
        rows.append(
            {
                **item,
                "sorted": sum(results[r] for r in HANDLED_RESULTS),
                "passed_on": sum(results[r] for r in NEEDED_PERSON),
                "no_conversation": sum(results[r] for r in UNREACHED_RESULTS),
            }
        )
    return {"types": rows}


def call_spikes(calls: Sequence[ReportCall], span: Span) -> dict[str, Any]:
    """Calls by hour of day, and the hours that had far more calls than
    usual (``SPIKE_*``): on a support line, often an outage. Only volume is
    counted; nothing says what the calls were about."""
    by_hour = [0] * 24
    per_slot: Counter[datetime] = Counter()
    for call in calls:
        local = _local(call, span)
        by_hour[local.hour] += 1
        per_slot[local.replace(minute=0, second=0, microsecond=0)] += 1
    days = max(1, span.days)
    spikes = []
    for slot, n in per_slot.items():
        usual = by_hour[slot.hour] / days
        if n >= SPIKE_MIN_CALLS and n >= SPIKE_FACTOR * usual:
            spikes.append({"at": slot, "calls": n, "usual": round(usual, 1)})
    spikes.sort(key=lambda s: (-s["calls"], s["at"]))
    return {"by_hour": by_hour, "spikes": spikes[:5], "days": days}


def repeat_callers(calls: Sequence[ReportCall]) -> dict[str, Any]:
    """Numbers that rang more than once in the period (withheld numbers
    can't be matched and are left out)."""
    by_number: dict[str, list[ReportCall]] = {}
    for call in calls:
        key = number_key(call.view.caller_number)
        if key is not None:
            by_number.setdefault(key, []).append(call)
    repeats = [group for group in by_number.values() if len(group) > 1]
    repeats.sort(
        key=lambda g: (-len(g), -max(c.view.created_at for c in g).timestamp())
    )
    items = []
    for group in repeats[:MAX_LIST]:
        latest = max(group, key=lambda c: c.view.created_at)
        name = next((c.view.caller_name for c in group if c.view.caller_name), None)
        items.append(
            {
                "caller_name": name,
                "caller_number": latest.view.caller_number,
                "calls": len(group),
                "last_at": latest.view.created_at,
                "last_run_id": latest.view.run_id,
                "reached": latest.result not in UNREACHED_RESULTS,
            }
        )
    return {
        "callers": len(repeats),
        "calls": sum(len(g) for g in repeats),
        "items": items,
    }


# ---------------------------------------------------------- estimates


def estimate(
    average: Decimal | None, units: int, previous_units: int, unit: str
) -> dict[str, Any] | None:
    """units × the owner's own average; None until they give one."""
    if average is None:
        return None
    value = (average * units).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    before = (average * previous_units).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return {
        "average": average,
        "units": units,
        "unit": unit,
        "value": value,
        "previous_value": before,
        "change": value - before
        if call_change(units, previous_units) is not None
        else None,
    }


# --------------------------------------------------------------- packs


def build_cards(
    *,
    pack: PackSpec,
    reasons: ReasonSet,
    calls: Sequence[ReportCall],
    previous: Sequence[ReportCall],
    span: Span,
    average: Decimal | None = None,
    wanted: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Each of the pack's cards (or just *wanted*) by key. A card whose data
    doesn't exist for this business (no takeaway reason, no average given)
    is None."""
    keys = [k for k in pack.keys if wanted is None or k in set(wanted)]
    out: dict[str, Any] = {}
    # Callers turned away because every line was busy never reached the
    # agent: they have their own card (and their follow-ups), and are left
    # out of the cards about the calls the agent took.
    every_call = calls
    calls = [c for c in calls if not c.view.lines_busy]
    previous = [c for c in previous if not c.view.lines_busy]
    split: dict[str, Any] | None = None

    def booked_units(of: Sequence[ReportCall]) -> int:
        return len(_booked(of))

    for key in keys:
        if key == Card.CALLS_ANSWERED:
            out[key] = calls_answered(calls, previous, span)
        elif key == Card.CALLERS_WANTED:
            out[key] = callers_wanted(calls, reasons, span)
        elif key == Card.BUSIEST_TIMES:
            out[key] = busiest_times(calls, span)
        elif key == Card.UNANSWERED_QUESTIONS:
            out[key] = unanswered(calls)
        elif key == Card.FOLLOW_UPS:
            out[key] = follow_up_stats(every_call)
        elif key == Card.LINES_BUSY:
            out[key] = lines_busy(every_call, span)
        elif key == Card.AFTER_HOURS:
            out[key] = after_hours(calls, span)
        elif key == Card.AGENT_PERFORMANCE:
            out[key] = agent_performance(calls)
        elif key in (Card.BOOKINGS_TAKEN, Card.APPOINTMENTS_BOOKED):
            out[key] = bookings(calls, previous)
        elif key == Card.COVERS_BOOKED:
            out[key] = covers(calls, previous)
        elif key == Card.TABLES_FULL:
            out[key] = tables_full(calls, previous, span)
        elif key == Card.DAYS_FILLING:
            out[key] = days_filling(calls, span)
        elif key == Card.SPECIAL_REQUESTS:
            out[key] = special_requests(calls, reasons)
        elif key == Card.TAKEAWAY:
            out[key] = (
                _reason_card(calls, previous, "takeaway", span)
                if "takeaway" in reasons.keys
                else None
            )
        elif key == Card.BOOKINGS_VALUE:
            out[key] = estimate(
                average,
                _sizes(_booked(calls)).covers,
                _sizes(_booked(previous)).covers,
                "cover",
            )
        elif key == Card.APPOINTMENTS_VALUE:
            out[key] = estimate(
                average, booked_units(calls), booked_units(previous), "appointment"
            )
        elif key == Card.PATIENT_STATUS:
            out[key] = patient_status(calls)
        elif key == Card.APPOINTMENT_TYPES:
            out[key] = appointment_types(calls)
        elif key == Card.EMERGENCIES:
            out[key] = _reason_card(calls, previous, "urgent", span)
        elif key == Card.CHANGES:
            out[key] = _reason_card(calls, previous, "changes", span)
        elif key == Card.JOBS_QUOTES:
            out[key] = _reason_card(calls, previous, "new_job", span)
        elif key == Card.EMERGENCIES_BY_HOUR:
            out[key] = emergencies_by_hour(calls, span)
        elif key == Card.AREAS:
            out[key] = areas(calls)
        elif key in (Card.CALLBACKS_WAITING, Card.WAITING_FOR_TEAM):
            out[key] = waiting(calls, span)
        elif key == Card.AFTER_HOURS_CALLOUTS:
            out[key] = after_hours_callouts(calls, previous, span)
        elif key == Card.JOBS_VALUE:
            jobs = _reason_card(calls, previous, "new_job", span)
            out[key] = estimate(average, jobs["count"], jobs["previous"], "job")
        elif key in (Card.SORTED_BY_AGENT, Card.PASSED_ON):
            split = split or sorted_split(calls, previous)
            out[key] = split["sorted" if key == Card.SORTED_BY_AGENT else "passed_on"]
        elif key == Card.ISSUES_BY_TYPE:
            out[key] = issues_by_type(calls, reasons)
        elif key == Card.CALL_SPIKES:
            out[key] = call_spikes(calls, span)
        elif key == Card.REPEAT_CALLERS:
            out[key] = repeat_callers(calls)
        elif key in RETAIL_REASON_CARDS:
            out[key] = _reason_card(calls, previous, RETAIL_REASON_CARDS[key], span)
        elif key == Card.TOP_PRODUCTS:
            out[key] = top_products(calls)
    if not previous:
        # Nothing to compare with (a new business, or before its first
        # call): "up 115" against an empty period would only mislead.
        for card in out.values():
            _drop_changes(card)
    return out


def _drop_changes(value: Any) -> None:
    """Set every "change" in a card (and its nested parts) to None."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k == "change":
                value[k] = None
            else:
                _drop_changes(v)
    elif isinstance(value, list):
        for item in value:
            _drop_changes(item)


def local_day_bounds(
    first: date, last: date, tz: ZoneInfo
) -> tuple[datetime, datetime]:
    """[local midnight of *first*, local midnight after *last*)."""
    return (
        datetime.combine(first, time.min, tzinfo=tz),
        datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz),
    )
