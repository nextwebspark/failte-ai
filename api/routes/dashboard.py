"""Home (the dashboard) and Follow-ups."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.db import db_client
from api.services.auth.depends import OrgMembership, require_permission
from api.services.auth.permissions import Permission
from api.services.dashboard.calls import CallResult
from api.services.dashboard.follow_ups import (
    REVIEW_KINDS,
    FollowUpKind,
    FollowUpStatus,
    done_mark,
)
from api.services.dashboard.service import (
    dashboard_summary,
    follow_up_list,
    open_follow_up_count,
)
from api.services.dashboard.summary import DashboardRange, NotAnsweringReason

router = APIRouter(tags=["dashboard"])

# Every member reads Home and Follow-ups, staff included: the agent's status
# comes from here, not from telephony settings they may not read.
CallsReader = Annotated[
    OrgMembership, Depends(require_permission(Permission.CALLS_READ))
]
FollowUpsManager = Annotated[
    OrgMembership, Depends(require_permission(Permission.FOLLOWUPS_MANAGE))
]


class DashboardTiles(BaseModel):
    calls: int
    # Completed, not passed to a person, not a hang-up, and no follow-up needed.
    handled: int
    handled_percent: int | None
    # Transfers tried: picked up plus not answered.
    passed_to_team: int
    transfer_picked_up: int
    transfer_not_answered: int
    # The engine heard no speech from the caller.
    hung_up_silent: int
    callbacks_requested: int
    in_progress: int
    average_call_seconds: int | None
    # Bookings the calendar confirmed on the call.
    bookings_taken: int


class DashboardRecentCall(BaseModel):
    run_id: int
    workflow_id: int
    created_at: datetime
    caller_number: str | None
    caller_name: str | None
    result: CallResult
    duration_seconds: float | None
    has_recording: bool
    # From the call review; None until it is written.
    summary: str | None
    reason_label: str | None


class DashboardReason(BaseModel):
    # The reason's key in the agent's template set, or "not_reviewed".
    key: str
    label: str
    count: int
    percent: int


class DashboardWording(BaseModel):
    # The starter template category the words come from.
    template: str
    # "bookings taken", "appointments booked"; None when the agent doesn't book.
    bookings_label: str | None


class DashboardAgentStatus(BaseModel):
    answering: bool
    reason: NotAnsweringReason | None
    phone_numbers: list[str]
    last_call_at: datetime | None


class DashboardCredit(BaseModel):
    balance_eur: Decimal
    spendable_eur: Decimal
    rate_per_minute_eur: Decimal
    minutes_left: int | None
    too_low: bool
    running_low: bool


class DashboardAgent(BaseModel):
    id: int
    name: str
    active: bool


class DashboardAgentRef(BaseModel):
    id: int
    name: str


class DashboardAfterHours(BaseModel):
    # Calls that arrived while the business was closed, by each agent's
    # opening hours set as times; None when no agent has them.
    calls: int | None
    # Agents whose calls aren't counted: no opening hours set as times.
    agents_without_hours: list[DashboardAgentRef]


class DashboardSummaryResponse(BaseModel):
    range: DashboardRange
    timezone: str
    workflow_id: int | None
    start: datetime
    end: datetime
    tiles: DashboardTiles
    # Calls in the span compared against (see ``range``).
    previous_calls: int
    # None when both spans have too few calls to compare.
    calls_change: int | None
    # Calls per local hour of the day, 0-23, summed over the range.
    calls_by_hour: list[int]
    after_hours: DashboardAfterHours
    recent_calls: list[DashboardRecentCall]
    # What callers wanted, from the call reviews, most common first.
    callers_wanted: list[DashboardReason]
    wording: DashboardWording
    # Whether any real call ever came in (scoped like the rest).
    has_calls: bool
    agent_status: DashboardAgentStatus
    # None when calls aren't billed by prepaid credit, or the member can't
    # read billing.
    credit: DashboardCredit | None
    agents: list[DashboardAgent]


class FollowUpItem(BaseModel):
    run_id: int
    workflow_id: int
    workflow_name: str
    kind: FollowUpKind
    created_at: datetime
    caller_number: str | None
    caller_name: str | None
    callback_number: str | None
    call_reason: str | None
    duration_seconds: float | None
    has_recording: bool
    repeat_count: int | None
    first_call_at: datetime | None
    done_at: datetime | None
    done_by: str | None
    # From the call review, when written.
    summary: str | None
    # The questions the agent couldn't answer (``unanswered_question`` only).
    questions: list[str]


class FollowUpWeek(BaseModel):
    raised: int
    sorted: int
    median_wait_minutes: int | None


class FollowUpListResponse(BaseModel):
    status: FollowUpStatus
    items: list[FollowUpItem]
    kind_counts: dict[str, int]
    open_count: int
    done_count: int
    week: FollowUpWeek
    # Whether any real call ever came in (scoped like the list).
    has_calls: bool


class FollowUpCountResponse(BaseModel):
    open: int


class FollowUpMarkResponse(BaseModel):
    run_id: int
    kind: FollowUpKind | None = None
    done_at: datetime | None
    done_by: str | None


async def _check_workflow(organization_id: int, workflow_id: int | None) -> None:
    if workflow_id is None:
        return
    agents = await db_client.get_dashboard_agents(organization_id)
    if not any(a["id"] == workflow_id for a in agents):
        raise HTTPException(status_code=404, detail="Agent not found")


@router.get("/dashboard/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(
    membership: CallsReader,
    range: Annotated[DashboardRange, Query()] = DashboardRange.TODAY,
    workflow_id: Annotated[int | None, Query()] = None,
    timezone: Annotated[
        str | None,
        Query(description="IANA zone; defaults to the agent's or workspace's"),
    ] = None,
) -> DashboardSummaryResponse:
    """Home: today's (or the last 7 or 30 days') calls, counted from stored
    calls, and whether the agent is answering."""
    await _check_workflow(membership.organization_id, workflow_id)
    summary = await dashboard_summary(
        organization_id=membership.organization_id,
        range_=range,
        workflow_id=workflow_id,
        timezone=timezone,
        show_credit=membership.can(Permission.BILLING_READ),
    )
    return DashboardSummaryResponse(**summary)


@router.get("/follow-ups", response_model=FollowUpListResponse)
async def list_follow_ups(
    membership: CallsReader,
    status: Annotated[FollowUpStatus, Query()] = FollowUpStatus.OPEN,
    workflow_id: Annotated[int | None, Query()] = None,
) -> FollowUpListResponse:
    """Calls from the last 30 days that need a person."""
    await _check_workflow(membership.organization_id, workflow_id)
    result = await follow_up_list(
        organization_id=membership.organization_id,
        status=status,
        workflow_id=workflow_id,
    )
    return FollowUpListResponse(**result)


@router.get("/follow-ups/count", response_model=FollowUpCountResponse)
async def count_follow_ups(
    membership: CallsReader,
    workflow_id: Annotated[int | None, Query()] = None,
) -> FollowUpCountResponse:
    """How many follow-ups are waiting (the menu badge)."""
    await _check_workflow(membership.organization_id, workflow_id)
    return FollowUpCountResponse(
        open=await open_follow_up_count(
            organization_id=membership.organization_id, workflow_id=workflow_id
        )
    )


KindQuery = Annotated[
    FollowUpKind | None,
    Query(
        description=(
            "The follow-up's kind. Needed for the call-review kinds "
            "(unanswered_question, time_was_full), which are done on their own; "
            "the other kinds share one mark per call."
        )
    ),
]


def _mark_kind(kind: FollowUpKind | None) -> str | None:
    return kind.value if kind in REVIEW_KINDS else None


@router.post("/follow-ups/{run_id}/done", response_model=FollowUpMarkResponse)
async def mark_follow_up_done(
    run_id: int, membership: FollowUpsManager, kind: KindQuery = None
):
    """Mark a call's follow-up done, saying who and when."""
    mark = done_mark(
        user_id=membership.user.id,
        name=membership.user.name,
        email=membership.user.email,
        now=datetime.now(UTC),
    )
    if (
        await db_client.set_follow_up_mark(
            membership.organization_id, run_id, mark, kind=_mark_kind(kind)
        )
        is None
    ):
        raise HTTPException(status_code=404, detail="Call not found")
    return FollowUpMarkResponse(
        run_id=run_id,
        kind=kind,
        done_at=datetime.fromisoformat(mark["done_at"]),
        done_by=mark["done_by"],
    )


@router.delete("/follow-ups/{run_id}/done", response_model=FollowUpMarkResponse)
async def undo_follow_up_done(
    run_id: int, membership: FollowUpsManager, kind: KindQuery = None
):
    """Put a follow-up back on the to-do list."""
    if (
        await db_client.set_follow_up_mark(
            membership.organization_id, run_id, None, kind=_mark_kind(kind)
        )
        is None
    ):
        raise HTTPException(status_code=404, detail="Call not found")
    return FollowUpMarkResponse(run_id=run_id, kind=kind, done_at=None, done_by=None)
