"""Loads the calls and settings Home and Follow-ups count from."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from api.constants import BILLING_PROVIDER
from api.db import db_client
from api.services.billing import pricing
from api.services.dashboard.calls import CallView, call_view
from api.services.dashboard.follow_ups import (
    LOOKBACK,
    FollowUp,
    FollowUpStatus,
    follow_up_row,
    follow_ups,
    kind_counts,
    ordered,
    week_summary,
)
from api.services.dashboard.summary import (
    DashboardRange,
    agent_status,
    call_change,
    calls_by_hour,
    credit_summary,
    range_bounds,
    recent_calls,
    tiles,
)

DEFAULT_TIMEZONE = "Europe/Dublin"


def _zone(name: str | None) -> ZoneInfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


async def _organization_timezone(organization_id: int) -> str | None:
    # Imported here: organization_preferences pulls in the call-events stack.
    from api.services.organization_preferences import get_organization_preferences

    try:
        return (await get_organization_preferences(organization_id)).timezone
    except Exception:  # noqa: BLE001 - the default zone is a fine answer
        return None


async def resolve_timezone(
    organization_id: int,
    requested: str | None,
    workflow_id: int | None,
    agents: list[dict[str, Any]],
) -> ZoneInfo:
    """The asked-for zone, else the agent's (saved with its opening hours),
    else the workspace's, else the first agent's that has one, else Ireland."""
    zone = _zone(requested)
    if zone:
        return zone
    if workflow_id is not None:
        for agent in agents:
            if agent["id"] == workflow_id and (zone := _zone(agent.get("timezone"))):
                return zone
    if zone := _zone(await _organization_timezone(organization_id)):
        return zone
    for agent in agents:
        if zone := _zone(agent.get("timezone")):
            return zone
    return ZoneInfo(DEFAULT_TIMEZONE)


async def load_calls(
    organization_id: int,
    start: datetime,
    end: datetime,
    workflow_id: int | None,
    now: datetime,
) -> list[CallView]:
    rows = await db_client.get_inbound_calls_for_dashboard(
        organization_id,
        start.astimezone(UTC),
        end.astimezone(UTC),
        workflow_id=workflow_id,
    )
    logs = await db_client.get_call_logs([r["id"] for r in rows if r["transfer_hint"]])
    return [call_view(row, logs.get(row["id"]), now) for row in rows]


async def _credit(organization_id: int) -> dict[str, Any] | None:
    """Prepaid credit, when calls are billed through Stripe."""
    if BILLING_PROVIDER != "stripe":
        return None
    account = await db_client.get_billing_account(organization_id)
    if account is None:
        return None
    return credit_summary(
        balance_eur=account.balance_eur,
        credit_limit_eur=account.credit_limit_eur,
        rate_per_minute_eur=pricing.price_per_minute_eur(
            account.plan, account.price_per_minute_eur
        ),
        min_balance_for_call_eur=pricing.MIN_BALANCE_FOR_CALL_EUR,
        low_balance_warning_eur=pricing.LOW_BALANCE_WARNING_EUR,
    )


async def dashboard_summary(
    *,
    organization_id: int,
    range_: DashboardRange,
    workflow_id: int | None,
    timezone: str | None,
    show_credit: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    agents = await db_client.get_dashboard_agents(organization_id)
    tz = await resolve_timezone(organization_id, timezone, workflow_id, agents)
    bounds = range_bounds(range_, tz, now)

    calls = await load_calls(
        organization_id, bounds.start, bounds.end, workflow_id, now
    )
    previous_calls = await db_client.count_inbound_calls(
        organization_id,
        bounds.previous_start.astimezone(UTC),
        bounds.previous_end.astimezone(UTC),
        workflow_id=workflow_id,
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
    scoped_agents = [a for a in agents if workflow_id is None or a["id"] == workflow_id]
    return {
        "range": range_,
        "timezone": tz.key,
        "workflow_id": workflow_id,
        "start": bounds.start,
        "end": bounds.end,
        "tiles": tiles(calls),
        "previous_calls": previous_calls,
        "calls_change": call_change(len(calls), previous_calls),
        "calls_by_hour": calls_by_hour(calls, tz),
        "recent_calls": recent_calls(calls),
        "agent_status": status,
        "credit": credit if show_credit else None,
        "agents": [
            {"id": a["id"], "name": a["name"], "active": a.get("status") == "active"}
            for a in scoped_agents
        ],
    }


async def _follow_up_items(
    organization_id: int, workflow_id: int | None, now: datetime
) -> list[FollowUp]:
    calls = await load_calls(organization_id, now - LOOKBACK, now, workflow_id, now)
    return follow_ups(calls)


async def follow_up_list(
    *,
    organization_id: int,
    status: FollowUpStatus,
    workflow_id: int | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    items = await _follow_up_items(organization_id, workflow_id, now)
    shown = ordered(items, status)
    return {
        "status": status,
        "items": [follow_up_row(item) for item in shown],
        "kind_counts": kind_counts(shown),
        "open_count": sum(1 for i in items if not i.done),
        "done_count": sum(1 for i in items if i.done),
        "week": week_summary(items, now),
    }


async def open_follow_up_count(
    *, organization_id: int, workflow_id: int | None, now: datetime | None = None
) -> int:
    now = now or datetime.now(UTC)
    items = await _follow_up_items(organization_id, workflow_id, now)
    return sum(1 for i in items if not i.done)


async def open_follow_up_run_ids(
    *, organization_id: int, workflow_id: int | None = None, now: datetime | None = None
) -> list[int]:
    """The calls with an open follow-up, exactly as Follow-ups lists them
    (same window, kinds and done marks). The Calls page's "Needs follow-up"
    tab filters on these, so the two can't disagree."""
    now = now or datetime.now(UTC)
    items = await _follow_up_items(organization_id, workflow_id, now)
    return sorted({i.call.run_id for i in items if not i.done})
