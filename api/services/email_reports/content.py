"""The numbers in one report email, counted with the dashboard's own rules
(``api.services.dashboard``), never recounted differently. Only stored calls
are read; the browser-only sample calls never reach this code.

``build_report`` is pure; ``load_report`` does the reading.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from api.services.dashboard.calls import CallResult, CallView, call_view
from api.services.dashboard.follow_ups import FollowUpStatus
from api.services.dashboard.summary import call_change, calls_by_hour, tiles
from api.services.email_reports.periods import Frequency, Period

TOP_FOLLOW_UPS = 5
TOP_REASONS = 6
REVIEW_ANNOTATION = "call_review"


@dataclass(frozen=True, slots=True)
class Bar:
    label: str
    count: int


@dataclass(frozen=True, slots=True)
class FollowUpLine:
    caller_name: str | None
    caller_number: str | None
    reason: str | None
    kind: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Report:
    business_name: str
    agent_name: str | None
    period: Period
    tz: ZoneInfo
    calls: int
    handled: int
    passed_to_team: int
    hung_up_silent: int
    bookings: int
    average_call_seconds: int | None
    calls_change: int | None
    open_follow_ups: int
    follow_ups: list[FollowUpLine]
    callers_wanted: list[Bar]
    # Hours for a daily report, days for weekly and monthly.
    when: list[Bar]
    # Why the agent isn't answering (the dashboard's reason), else None.
    not_answering: str | None
    credit: Mapping[str, Any] | None = None


def callers_wanted(rows: Sequence[Mapping[str, Any]]) -> list[Bar]:
    """What callers rang about, from each call's stored AI review
    (``annotations.call_review.reason_label``). Calls without a review are
    left out; nothing is guessed."""
    counts: Counter[str] = Counter()
    for row in rows:
        review = (row.get("annotations") or {}).get(REVIEW_ANNOTATION)
        if not isinstance(review, Mapping):
            continue
        label = review.get("reason_label")
        if isinstance(label, str) and label.strip():
            counts[label.strip()[:60]] += 1
    return [Bar(label, count) for label, count in counts.most_common(TOP_REASONS)]


def hour_bars(calls: Sequence[CallView], tz: ZoneInfo) -> list[Bar]:
    """One bar per hour, trimmed to the hours with calls but never narrower
    than 8 am to 6 pm, so a quiet day still reads as a working day."""
    hours = calls_by_hour(calls, tz)
    busy = [h for h, n in enumerate(hours) if n]
    first = min([8, *busy])
    last = max([18, *busy])
    return [Bar(str(h), hours[h]) for h in range(first, last + 1)]


def day_bars(calls: Sequence[CallView], period: Period, tz: ZoneInfo) -> list[Bar]:
    counts: Counter = Counter(c.created_at.astimezone(tz).date() for c in calls)
    bars: list[Bar] = []
    day = period.start.date()
    last = (period.end - timedelta(microseconds=1)).astimezone(tz).date()
    while day <= last:
        bars.append(Bar(day.isoformat(), counts.get(day, 0)))
        day += timedelta(days=1)
    return bars


def build_report(
    *,
    business_name: str,
    agent_name: str | None,
    period: Period,
    tz: ZoneInfo,
    calls: Sequence[CallView],
    rows: Sequence[Mapping[str, Any]],
    previous_calls: int,
    follow_up_rows: Sequence[Mapping[str, Any]],
    open_follow_ups: int,
    agent_status: Mapping[str, Any] | None,
    credit: Mapping[str, Any] | None,
) -> Report:
    counted = tiles(calls)
    when = (
        hour_bars(calls, tz)
        if period.frequency == Frequency.DAILY
        else day_bars(calls, period, tz)
    )
    reason = None
    if agent_status is not None and not agent_status.get("answering", True):
        raw = agent_status.get("reason")
        reason = getattr(raw, "value", raw)
    return Report(
        business_name=business_name,
        agent_name=agent_name,
        period=period,
        tz=tz,
        calls=counted["calls"],
        handled=counted["handled"],
        passed_to_team=counted["passed_to_team"],
        hung_up_silent=counted["hung_up_silent"],
        bookings=sum(1 for c in calls if c.result == CallResult.BOOKING_MADE),
        average_call_seconds=counted["average_call_seconds"],
        calls_change=call_change(counted["calls"], previous_calls),
        open_follow_ups=open_follow_ups,
        follow_ups=[
            FollowUpLine(
                caller_name=row.get("caller_name"),
                caller_number=row.get("callback_number") or row.get("caller_number"),
                reason=row.get("call_reason"),
                kind=str(getattr(row.get("kind"), "value", row.get("kind"))),
                created_at=row["created_at"],
            )
            for row in list(follow_up_rows)[:TOP_FOLLOW_UPS]
        ],
        callers_wanted=callers_wanted(rows),
        when=when,
        not_answering=reason,
        credit=credit,
    )


async def load_report(
    *,
    organization_id: int,
    business_name: str,
    workflow_id: int | None,
    period: Period,
    tz: ZoneInfo,
    agents: Sequence[Mapping[str, Any]],
    now: datetime | None = None,
) -> Report:
    """Read the period's calls and the workspace's state and build the
    report. Credit is always loaded; the sender drops it for recipients who
    may not see billing."""
    from api.db import db_client
    from api.services.dashboard.service import _credit, follow_up_list
    from api.services.dashboard.summary import agent_status

    now = now or datetime.now(UTC)
    rows = await db_client.get_inbound_calls_for_dashboard(
        organization_id,
        period.start.astimezone(UTC),
        period.end.astimezone(UTC),
        workflow_id=workflow_id,
    )
    logs = await db_client.get_call_logs([r["id"] for r in rows if r["transfer_hint"]])
    calls = [call_view(row, logs.get(row["id"]), now) for row in rows]
    previous_calls = await db_client.count_inbound_calls(
        organization_id,
        period.previous_start.astimezone(UTC),
        period.previous_end.astimezone(UTC),
        workflow_id=workflow_id,
    )
    follow_up = await follow_up_list(
        organization_id=organization_id,
        status=FollowUpStatus.OPEN,
        workflow_id=workflow_id,
        now=now,
    )
    credit = await _credit(organization_id)
    status = agent_status(
        agents=agents,
        numbers=await db_client.get_answering_numbers(organization_id),
        workflow_id=workflow_id,
        credit_too_low=bool(credit and credit["too_low"]),
        last_call_at=await db_client.get_last_inbound_call_at(
            organization_id, workflow_id
        ),
    )
    agent_name = next(
        (
            a["name"]
            for a in agents
            if workflow_id is not None and a["id"] == workflow_id
        ),
        None,
    )
    return build_report(
        business_name=business_name,
        agent_name=agent_name,
        period=period,
        tz=tz,
        calls=calls,
        rows=rows,
        previous_calls=previous_calls,
        follow_up_rows=follow_up["items"],
        open_follow_ups=follow_up["open_count"],
        agent_status=status,
        credit=credit,
    )
