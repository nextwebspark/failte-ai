"""Loads what the report cards are counted from: the calls (as Home loads
them, plus what the agent wrote down), the agents' opening hours, the pack
and the owner's layout."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from api.db import db_client
from api.schemas.opening_hours import OpeningHours
from api.services.call_review.categories import (
    ReasonSet,
    reason_set,
    template_for_workflow,
)
from api.services.dashboard.calls import call_view
from api.services.dashboard.summary import DashboardRange, range_bounds
from api.services.report_cards.cards import ReportCall, Span, build_cards
from api.services.report_cards.catalogue import PackSpec, pack_for_template
from api.services.report_cards.layout import (
    LAYOUT_KEY,
    CardChoice,
    StoredLayout,
    average,
    default_cards,
    effective_cards,
    parse_layout,
)
from api.services.workflow.opening_hours import parse_opening_hours

# The longest span a custom range may cover.
MAX_CUSTOM_DAYS = 366


class ReportRange(StrEnum):
    TODAY = "today"
    LAST_7_DAYS = "7d"
    LAST_30_DAYS = "30d"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class Bounds:
    start: datetime
    end: datetime
    previous_start: datetime
    previous_end: datetime


class RangeError(ValueError):
    pass


def report_bounds(
    range_: ReportRange,
    tz: ZoneInfo,
    now: datetime,
    start_date: date | None = None,
    end_date: date | None = None,
) -> Bounds:
    """Today, 7 and 30 days are Home's own spans and comparisons (Today
    against the same hours a week ago; 7 and 30 days against the same number
    of days just before). A custom range runs from local midnight of its
    first day to local midnight after its last, or to now if that is
    sooner, and is compared with a span of exactly the same length just
    before it."""
    if range_ != ReportRange.CUSTOM:
        b = range_bounds(DashboardRange(range_.value), tz, now)
        return Bounds(b.start, b.end, b.previous_start, b.previous_end)
    if start_date is None:
        raise RangeError("Pick the first day.")
    last = end_date or start_date
    if last < start_date:
        raise RangeError("The last day is before the first.")
    today = now.astimezone(tz).date()
    if start_date > today:
        raise RangeError("Pick days up to today.")
    if (last - start_date).days + 1 > MAX_CUSTOM_DAYS:
        raise RangeError("Pick at most a year.")
    start = datetime.combine(start_date, datetime.min.time(), tzinfo=tz)
    end = min(
        datetime.combine(last + timedelta(days=1), datetime.min.time(), tzinfo=tz),
        now,
    )
    length = end - start
    return Bounds(start, end, start - length, start)


async def load_report_calls(
    organization_id: int,
    start: datetime,
    end: datetime,
    workflow_id: int | None,
    now: datetime,
) -> list[ReportCall]:
    """The inbound calls in ``[start, end)``, exactly the ones Home counts,
    newest first, each with what the agent wrote down."""
    rows = await db_client.get_inbound_calls_for_dashboard(
        organization_id,
        start.astimezone(UTC),
        end.astimezone(UTC),
        workflow_id=workflow_id,
    )
    logs = await db_client.get_call_logs([r["id"] for r in rows if r["transfer_hint"]])
    return [
        ReportCall(
            view=call_view(row, logs.get(row["id"]), now),
            gathered=row.get("gathered_context") or {},
        )
        for row in rows
    ]


async def resolve_pack(
    organization_id: int, workflow_id: int | None, agents: Sequence[Mapping[str, Any]]
) -> tuple[str, PackSpec, ReasonSet]:
    """The template of the agent shown (or, for all agents, the first one
    that is switched on, as Home picks its wording), and its pack."""
    agent_id = workflow_id
    if agent_id is None:
        active = [a for a in agents if a.get("status") == "active"]
        agent_id = (active or list(agents) or [{"id": None}])[0]["id"]
    source = (
        await db_client.get_agent_template_source(organization_id, agent_id)
        if agent_id is not None
        else None
    )
    template = (
        template_for_workflow(source["definition"], source["facts"])
        if source
        else "general"
    )
    return template, pack_for_template(template), reason_set(template)


async def load_layout(organization_id: int) -> StoredLayout:
    row = await db_client.get_configuration(organization_id, LAYOUT_KEY)
    return parse_layout(row.value if row is not None else None, organization_id)


async def change_layout(
    organization_id: int, change: Callable[[StoredLayout], StoredLayout]
) -> StoredLayout:
    """Apply *change* to the stored layout under the row lock."""

    def mutate(value: dict) -> tuple[dict, StoredLayout]:
        layout = change(parse_layout(value, organization_id))
        layout = StoredLayout.model_validate(layout.model_dump())
        return layout.model_dump(mode="json"), layout

    return await db_client.update_configuration_locked(
        organization_id, LAYOUT_KEY, mutate
    )


def opening_hours_of(
    agents: Sequence[Mapping[str, Any]], calls: Sequence[ReportCall]
) -> tuple[dict[int, OpeningHours], list[str]]:
    """Each agent's opening hours set as times, and the names of agents
    without them that are switched on or had calls (as Home lists them)."""
    hours = {
        a["id"]: parsed
        for a in agents
        if (parsed := parse_opening_hours(a.get("opening_hours_schedule")))
    }
    with_calls = {c.view.workflow_id for c in calls}
    missing = [
        a["name"]
        for a in agents
        if a["id"] not in hours
        and (a.get("status") == "active" or a["id"] in with_calls)
    ]
    return hours, missing


def layout_view(
    pack: PackSpec, stored: StoredLayout, *, can_customise: bool
) -> dict[str, Any]:
    cards = effective_cards(pack, stored)
    saved = stored.packs.get(pack.pack.value)
    return {
        "cards": [_card_view(pack, c) for c in cards],
        "defaults": [_card_view(pack, c) for c in default_cards(pack)],
        "average": average(pack, stored),
        "value_unit": pack.value_unit,
        "value_label": pack.value_label,
        "customised": saved is not None,
        "updated_at": saved.updated_at if saved else None,
        "updated_by": saved.updated_by if saved else None,
        "can_customise": can_customise,
    }


def _card_view(pack: PackSpec, choice: CardChoice) -> dict[str, Any]:
    spec = pack.spec(choice.key)
    assert spec is not None
    return {
        "key": spec.key.value,
        "title": spec.title,
        "size": spec.size,
        "estimate": spec.estimate,
        "on": choice.on,
        "email": choice.email,
    }


async def report_cards_for(
    *,
    organization_id: int,
    workflow_id: int | None,
    bounds: Bounds,
    tz: ZoneInfo,
    agents: Sequence[Mapping[str, Any]],
    now: datetime,
    wanted: Callable[[list[CardChoice]], list[str]],
) -> dict[str, Any]:
    """The pack's cards for a span. *wanted* picks the cards to count from
    the owner's layout (on the page: the ones switched on; in the email:
    the ones ticked for it)."""
    template, pack, reasons = await resolve_pack(organization_id, workflow_id, agents)
    stored = await load_layout(organization_id)
    choices = effective_cards(pack, stored)
    calls = await load_report_calls(
        organization_id, bounds.start, bounds.end, workflow_id, now
    )
    previous = await load_report_calls(
        organization_id, bounds.previous_start, bounds.previous_end, workflow_id, now
    )
    scoped = [a for a in agents if workflow_id is None or a["id"] == workflow_id]
    hours, without = opening_hours_of(scoped, calls)
    span = Span(
        start=bounds.start,
        end=bounds.end,
        previous_start=bounds.previous_start,
        previous_end=bounds.previous_end,
        tz=tz,
        now=now,
        hours=hours,
        agents_without_hours=without,
    )
    keys = wanted(choices)
    return {
        "template": template,
        "pack": pack,
        "reasons": reasons,
        "stored": stored,
        "choices": choices,
        "calls": calls,
        "span": span,
        "cards": build_cards(
            pack=pack,
            reasons=reasons,
            calls=calls,
            previous=previous,
            span=span,
            average=average(pack, stored),
            wanted=keys,
        ),
        "order": keys,
    }


async def report_overview(
    *,
    organization_id: int,
    range_: ReportRange,
    start_date: date | None,
    end_date: date | None,
    workflow_id: int | None,
    timezone: str | None,
    can_customise: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    from api.services.dashboard.service import resolve_timezone

    now = now or datetime.now(UTC)
    agents = await db_client.get_dashboard_agents(organization_id)
    tz = await resolve_timezone(organization_id, timezone, workflow_id, agents)
    bounds = report_bounds(range_, tz, now, start_date, end_date)
    built = await report_cards_for(
        organization_id=organization_id,
        workflow_id=workflow_id,
        bounds=bounds,
        tz=tz,
        agents=agents,
        now=now,
        # Every card: the Customise drawer previews any it switches on.
        wanted=lambda choices: [c.key for c in choices],
    )
    pack: PackSpec = built["pack"]
    return {
        "range": range_,
        "timezone": tz.key,
        "workflow_id": workflow_id,
        "start": bounds.start,
        "end": bounds.end,
        "previous_start": bounds.previous_start,
        "previous_end": bounds.previous_end,
        "template": built["template"],
        "pack": pack.pack,
        "pack_label": pack.label,
        "calls": len(built["calls"]),
        "has_calls": await db_client.get_last_inbound_call_at(
            organization_id, workflow_id
        )
        is not None,
        "agents": [
            {"id": a["id"], "name": a["name"], "active": a.get("status") == "active"}
            for a in agents
        ],
        "layout": layout_view(pack, built["stored"], can_customise=can_customise),
        "cards": built["cards"],
    }


async def report_calls(
    *,
    organization_id: int,
    range_: ReportRange,
    start_date: date | None,
    end_date: date | None,
    workflow_id: int | None,
    timezone: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The calls a report counts, for the download, oldest first."""
    from api.services.dashboard.service import resolve_timezone

    now = now or datetime.now(UTC)
    agents = await db_client.get_dashboard_agents(organization_id)
    tz = await resolve_timezone(organization_id, timezone, workflow_id, agents)
    bounds = report_bounds(range_, tz, now, start_date, end_date)
    calls = await load_report_calls(
        organization_id, bounds.start, bounds.end, workflow_id, now
    )
    return {
        "timezone": tz.key,
        "start": bounds.start,
        "end": bounds.end,
        "calls": [
            {
                "run_id": c.view.run_id,
                "workflow_id": c.view.workflow_id,
                "workflow_name": c.view.workflow_name,
                "created_at": c.view.created_at,
                "caller_number": c.view.caller_number,
                "caller_name": c.view.caller_name,
                "result": c.view.result,
                "reason_label": (c.view.review or {}).get("reason_label")
                if isinstance((c.view.review or {}).get("reason_label"), str)
                else None,
                "duration_seconds": c.view.duration_seconds,
            }
            for c in reversed(calls)
        ],
    }
