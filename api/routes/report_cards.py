"""Reports: each kind of business's own report pack, the owner's layout,
and the calls behind it for the download."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.db import db_client
from api.services.auth.depends import OrgMembership, require_permission
from api.services.auth.permissions import Permission
from api.services.dashboard.calls import CallResult
from api.services.dashboard.follow_ups import FollowUpKind
from api.services.report_cards.catalogue import CardSize, Pack
from api.services.report_cards.layout import (
    CardChoice,
    LayoutError,
    reset_pack,
    save_pack,
)
from api.services.report_cards.service import (
    RangeError,
    ReportRange,
    change_layout,
    layout_view,
    report_calls,
    report_overview,
    resolve_pack,
)

router = APIRouter(prefix="/organizations/reports", tags=["reports"])

# Every member reads reports; changing what everyone sees is the owner's
# (or an admin's), like choosing who gets them by email.
ReportsReader = Annotated[
    OrgMembership, Depends(require_permission(Permission.REPORTS_READ))
]
ReportsEditor = Annotated[
    OrgMembership, Depends(require_permission(Permission.REPORTS_SCHEDULE))
]


# ------------------------------------------------------------------ cards


class CardChange(BaseModel):
    previous: int
    # None when both spans are too small to compare (Home's rule).
    change: int | None


class CallsAnsweredCard(CardChange):
    calls: int
    # Came in while closed; None when no agent has opening hours as times.
    after_hours: int | None


class ReasonSeries(BaseModel):
    key: str
    label: str
    count: int


class ReasonBucket(BaseModel):
    date: date | None
    hour: int | None
    counts: dict[str, int]
    total: int


class CallersWantedCard(BaseModel):
    unit: str
    series: list[ReasonSeries]
    buckets: list[ReasonBucket]


class BusiestTip(BaseModel):
    # Monday 0 .. Sunday 6
    weekday: int
    start_hour: int
    end_hour: int
    calls: int
    one_in: int


class BusiestTimesCard(BaseModel):
    # [weekday][hour], Monday first, local time.
    grid: list[list[int]]
    first_hour: int
    last_hour: int
    max: int
    calls: int
    tip: BusiestTip | None


class QuestionGroup(BaseModel):
    question: str
    count: int
    run_id: int
    workflow_id: int
    last_asked_at: datetime
    answered: bool


class UnansweredCard(BaseModel):
    calls: int
    groups: list[QuestionGroup]
    more: int


class KindCount(BaseModel):
    kind: FollowUpKind
    count: int


class FollowUpsCard(BaseModel):
    raised: int
    sorted: int
    open: int
    median_wait_minutes: int | None
    kinds: list[KindCount]


class AfterHoursCard(BaseModel):
    hours_set: bool
    calls: int | None
    bookings: int | None
    callbacks: int | None
    handled: int | None
    agents_without_hours: list[str]


class AgentPerformanceCard(BaseModel):
    calls: int
    handled: int
    handled_percent: int | None
    needed_person: int
    passed_to_team: int
    callbacks: int
    no_conversation: int
    hung_up_silent: int
    in_progress: int
    results: dict[str, int]


class BookingsCard(CardChange):
    count: int
    percent_of_calls: int | None


class CoversCard(CardChange):
    covers: int
    bookings_with_size: int
    not_given: int
    unreadable: int
    average_party: float | None


class TablesFullCard(CardChange):
    count: int
    covers: int
    without_size: int
    mostly_days: list[int]
    mostly_hour: int | None


class FillingDay(BaseModel):
    date: date
    covers: int
    bookings: int
    closed: bool


class DaysFillingCard(BaseModel):
    days: list[FillingDay]
    without_size: int
    without_day: int
    later: int


class TagCount(BaseModel):
    key: str
    label: str
    count: int


class SpecialRequestsCard(BaseModel):
    tags: list[TagCount]
    calls_with_requests: int
    tagged_calls: int
    # Reviewed before tags existed, but a request was written down.
    not_tagged: int


class ReasonCard(CardChange):
    count: int
    handled: int
    booked: int
    passed_to_team: int
    callbacks: int
    needed_person: int
    after_hours: int | None


class EstimateCard(BaseModel):
    average: Decimal
    units: int
    unit: str
    value: Decimal
    previous_value: Decimal
    change: Decimal | None


class PatientStatusCard(BaseModel):
    new: int
    existing: int
    other: int
    booked_not_said: int


class AppointmentType(BaseModel):
    label: str
    calls: int
    booked: int


class AppointmentTypesCard(BaseModel):
    types: list[AppointmentType]
    other_calls: int


class EmergenciesByHourCard(BaseModel):
    hours: list[int]
    count: int
    after_hours: int | None
    peak_hour: int | None


class AreaCount(BaseModel):
    label: str
    count: int


class AreasCard(BaseModel):
    areas: list[AreaCount]
    other_areas: int
    places: int
    unclear: int
    with_address: int


class WaitingItem(BaseModel):
    run_id: int
    kind: FollowUpKind
    caller_name: str | None
    caller_number: str | None
    about: str | None
    area: str | None
    created_at: datetime


class WaitingCard(BaseModel):
    count: int
    oldest_minutes: int | None
    items: list[WaitingItem]


class CalloutsCard(BaseModel):
    hours_set: bool
    count: int | None
    previous: int
    change: int | None
    passed_to_team: int | None = None
    callbacks: int | None = None


class ShareCard(CardChange):
    count: int
    percent: int | None


class IssueType(BaseModel):
    key: str
    label: str
    count: int
    sorted: int
    passed_on: int
    no_conversation: int


class IssuesCard(BaseModel):
    types: list[IssueType]


class Spike(BaseModel):
    at: datetime
    calls: int
    usual: float


class SpikesCard(BaseModel):
    by_hour: list[int]
    spikes: list[Spike]
    days: int


class RepeatCaller(BaseModel):
    caller_name: str | None
    caller_number: str | None
    calls: int
    last_at: datetime
    last_run_id: int
    reached: bool


class RepeatCallersCard(BaseModel):
    callers: int
    calls: int
    items: list[RepeatCaller]


class ReportCards(BaseModel):
    """Each card the pack has, by key; absent (None) when the pack doesn't
    have it or its data doesn't exist for this business."""

    calls_answered: CallsAnsweredCard | None = None
    callers_wanted: CallersWantedCard | None = None
    busiest_times: BusiestTimesCard | None = None
    unanswered_questions: UnansweredCard | None = None
    follow_ups: FollowUpsCard | None = None
    after_hours: AfterHoursCard | None = None
    agent_performance: AgentPerformanceCard | None = None
    bookings_taken: BookingsCard | None = None
    covers_booked: CoversCard | None = None
    tables_full: TablesFullCard | None = None
    days_filling: DaysFillingCard | None = None
    special_requests: SpecialRequestsCard | None = None
    takeaway: ReasonCard | None = None
    bookings_value: EstimateCard | None = None
    appointments_booked: BookingsCard | None = None
    patient_status: PatientStatusCard | None = None
    appointment_types: AppointmentTypesCard | None = None
    emergencies: ReasonCard | None = None
    changes: ReasonCard | None = None
    appointments_value: EstimateCard | None = None
    jobs_quotes: ReasonCard | None = None
    emergencies_by_hour: EmergenciesByHourCard | None = None
    areas: AreasCard | None = None
    callbacks_waiting: WaitingCard | None = None
    after_hours_callouts: CalloutsCard | None = None
    jobs_value: EstimateCard | None = None
    sorted_by_agent: ShareCard | None = None
    passed_on: ShareCard | None = None
    issues_by_type: IssuesCard | None = None
    call_spikes: SpikesCard | None = None
    repeat_callers: RepeatCallersCard | None = None
    waiting_for_team: WaitingCard | None = None


# ----------------------------------------------------------------- layout


class ReportCardView(BaseModel):
    key: str
    title: str
    size: CardSize
    # A money estimate: shown only once the owner gives their average.
    estimate: bool
    on: bool
    email: bool


class ReportLayoutView(BaseModel):
    cards: list[ReportCardView]
    # The pack's own cards, for "Reset to the pack".
    defaults: list[ReportCardView]
    # The owner's own average for the money estimate, in euro.
    average: Decimal | None
    value_unit: str | None
    value_label: str | None
    customised: bool
    updated_at: datetime | None
    updated_by: str | None
    can_customise: bool


class ReportPageAgent(BaseModel):
    id: int
    name: str
    active: bool


class ReportOverviewResponse(BaseModel):
    range: ReportRange
    timezone: str
    workflow_id: int | None
    start: datetime
    end: datetime
    previous_start: datetime
    previous_end: datetime
    template: str
    pack: Pack
    pack_label: str
    calls: int
    has_calls: bool
    agents: list[ReportPageAgent]
    layout: ReportLayoutView
    cards: ReportCards


class ReportCardChoice(BaseModel):
    key: str
    on: bool = True
    email: bool = False


class ReportLayoutUpdate(BaseModel):
    workflow_id: int | None = None
    cards: list[ReportCardChoice] = Field(max_length=60)
    average: Decimal | None = Field(default=None, ge=0, le=100000)


class ReportCallRow(BaseModel):
    run_id: int
    workflow_id: int
    workflow_name: str
    created_at: datetime
    caller_number: str | None
    caller_name: str | None
    result: CallResult
    reason_label: str | None
    duration_seconds: float | None


class ReportCallsResponse(BaseModel):
    timezone: str
    start: datetime
    end: datetime
    calls: list[ReportCallRow]


# ----------------------------------------------------------------- routes


async def _check_workflow(organization_id: int, workflow_id: int | None) -> list:
    agents = await db_client.get_dashboard_agents(organization_id)
    if workflow_id is not None and not any(a["id"] == workflow_id for a in agents):
        raise HTTPException(status_code=404, detail="Agent not found")
    return agents


RangeQuery = Annotated[ReportRange, Query()]
DayQuery = Annotated[date | None, Query()]
WorkflowQuery = Annotated[int | None, Query()]
ZoneQuery = Annotated[
    str | None, Query(description="IANA zone; defaults to the agent's or workspace's")
]


@router.get("/overview", response_model=ReportOverviewResponse)
async def get_report_overview(
    membership: ReportsReader,
    range: RangeQuery = ReportRange.LAST_7_DAYS,
    start_date: DayQuery = None,
    end_date: DayQuery = None,
    workflow_id: WorkflowQuery = None,
    timezone: ZoneQuery = None,
) -> Any:
    """The report: the pack for the agent's kind of business, its cards
    counted for the period, and the owner's layout."""
    await _check_workflow(membership.organization_id, workflow_id)
    try:
        return await report_overview(
            organization_id=membership.organization_id,
            range_=range,
            start_date=start_date,
            end_date=end_date,
            workflow_id=workflow_id,
            timezone=timezone,
            can_customise=membership.can(Permission.REPORTS_SCHEDULE),
        )
    except RangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/calls", response_model=ReportCallsResponse)
async def get_report_calls(
    membership: ReportsReader,
    range: RangeQuery = ReportRange.LAST_7_DAYS,
    start_date: DayQuery = None,
    end_date: DayQuery = None,
    workflow_id: WorkflowQuery = None,
    timezone: ZoneQuery = None,
) -> Any:
    """The calls the report counts, oldest first, for the download."""
    await _check_workflow(membership.organization_id, workflow_id)
    try:
        return await report_calls(
            organization_id=membership.organization_id,
            range_=range,
            start_date=start_date,
            end_date=end_date,
            workflow_id=workflow_id,
            timezone=timezone,
        )
    except RangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _who(membership: OrgMembership) -> str | None:
    user = membership.user
    return (user.name or "").strip() or (user.email or "").split("@")[0] or None


@router.put("/layout", response_model=ReportLayoutView)
async def save_report_layout(body: ReportLayoutUpdate, membership: ReportsEditor):
    """Save which cards are on, their order, which go in the email and the
    owner's average, for the pack of the agent shown (or all agents)."""
    agents = await _check_workflow(membership.organization_id, body.workflow_id)
    _, pack, _ = await resolve_pack(
        membership.organization_id, body.workflow_id, agents
    )
    choices = [CardChoice(key=c.key, on=c.on, email=c.email) for c in body.cards]
    average = body.average if body.average else None
    try:
        stored = await change_layout(
            membership.organization_id,
            lambda layout: save_pack(
                layout,
                pack,
                choices,
                average,
                by=_who(membership),
                now=datetime.now(UTC),
            ),
        )
    except LayoutError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return layout_view(pack, stored, can_customise=True)


@router.delete("/layout", response_model=ReportLayoutView)
async def reset_report_layout(
    membership: ReportsEditor, workflow_id: WorkflowQuery = None
):
    """Back to the pack's own cards (the owner's average stays)."""
    agents = await _check_workflow(membership.organization_id, workflow_id)
    _, pack, _ = await resolve_pack(membership.organization_id, workflow_id, agents)
    stored = await change_layout(
        membership.organization_id, lambda layout: reset_pack(layout, pack)
    )
    return layout_view(pack, stored, can_customise=True)
