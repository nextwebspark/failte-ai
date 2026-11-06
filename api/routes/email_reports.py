"""Settings > Reports by email, and the public confirm/unsubscribe links."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field

from api.db import db_client
from api.services.auth.depends import OrgMembership, require_permission
from api.services.auth.permissions import Permission
from api.services.email import get_email_sender
from api.services.email_reports import render, service
from api.services.email_reports.periods import Frequency
from api.services.email_reports.settings import (
    MAX_RECIPIENTS,
    EmailReportSettings,
    RecipientError,
    RecipientStatus,
    add_recipient,
    describe_changes,
    record_change,
    refresh_confirmation,
    remove_recipient,
)

router = APIRouter(prefix="/organizations/email-reports", tags=["email-reports"])
public_router = APIRouter(prefix="/public/email-reports", tags=["email-reports"])

ReportsReader = Annotated[
    OrgMembership, Depends(require_permission(Permission.REPORTS_READ))
]
ReportsScheduler = Annotated[
    OrgMembership, Depends(require_permission(Permission.REPORTS_SCHEDULE))
]

_CLOCK = r"^([01]\d|2[0-3]):[0-5]\d$"


class ReportRecipientView(BaseModel):
    id: str
    email: str
    status: RecipientStatus
    verified_via: Literal["account", "link"] | None
    added_at: datetime
    confirmed_at: datetime | None
    confirm_sent_at: datetime | None


class ReportAgent(BaseModel):
    id: int
    name: str


class EmailReportSettingsResponse(BaseModel):
    daily: bool
    weekly: bool
    monthly: bool
    daily_send_time: str
    workflow_id: int | None
    recipients: list[ReportRecipientView]
    max_recipients: int
    # The zone send times are read in (the dashboard's).
    timezone: str
    agents: list[ReportAgent]
    # The signed-in member's own verified address (added without a link),
    # or None when it isn't verified.
    own_email: str | None
    # Where "Send me a test now" goes.
    your_email: str | None
    can_edit: bool
    email_available: bool
    # Last period each report went out for ("2026-11-06", "2026-W45", "2026-10").
    last_sent: dict[str, str]


class EmailReportSettingsUpdate(BaseModel):
    daily: bool
    weekly: bool
    monthly: bool
    daily_send_time: str = Field(pattern=_CLOCK)
    workflow_id: int | None = None


class AddRecipientRequest(BaseModel):
    email: EmailStr


class AddRecipientResponse(BaseModel):
    recipient: ReportRecipientView
    # False when a confirmation was needed but couldn't be emailed.
    confirmation_sent: bool
    settings: EmailReportSettingsResponse


class TestReportRequest(BaseModel):
    frequency: Frequency


class TestReportResponse(BaseModel):
    sent_to: str


class LinkResult(BaseModel):
    status: Literal["confirmed", "already", "removed", "invalid"]
    business_name: str | None


def _delivers() -> bool:
    try:
        return get_email_sender().delivers
    except Exception:  # noqa: BLE001 - a misconfigured provider sends nothing
        return False


def _view(recipient) -> ReportRecipientView:
    return ReportRecipientView(
        **recipient.model_dump(include=set(ReportRecipientView.model_fields))
    )


def _who(membership: OrgMembership) -> str | None:
    user = membership.user
    return (user.name or "").strip() or user.email


async def _response(
    membership: OrgMembership, settings: EmailReportSettings
) -> EmailReportSettingsResponse:
    tz, agents = await service.report_zone(
        membership.organization_id, settings.workflow_id
    )
    return EmailReportSettingsResponse(
        daily=settings.daily,
        weekly=settings.weekly,
        monthly=settings.monthly,
        daily_send_time=settings.daily_send_time,
        workflow_id=settings.workflow_id,
        recipients=[_view(r) for r in settings.recipients],
        max_recipients=MAX_RECIPIENTS,
        timezone=tz.key,
        agents=[ReportAgent(id=a["id"], name=a["name"]) for a in agents],
        own_email=service.own_verified_email(membership.user),
        your_email=membership.user.email,
        can_edit=membership.can(Permission.REPORTS_SCHEDULE),
        email_available=_delivers(),
        last_sent=await service.last_sent(membership.organization_id),
    )


@router.get("", response_model=EmailReportSettingsResponse)
async def get_email_report_settings(membership: ReportsReader):
    """Which reports are emailed, when, and to whom."""
    settings = await service.load_settings(membership.organization_id)
    return await _response(membership, settings)


@router.put("", response_model=EmailReportSettingsResponse)
async def update_email_report_settings(
    request: EmailReportSettingsUpdate, membership: ReportsScheduler
):
    """Switch reports on or off, and choose the daily time and the agent."""
    if request.workflow_id is not None:
        agents = await db_client.get_dashboard_agents(membership.organization_id)
        if not any(a["id"] == request.workflow_id for a in agents):
            raise HTTPException(status_code=404, detail="Agent not found")

    def change(settings: EmailReportSettings):
        before = settings.model_copy(deep=True)
        settings.daily = request.daily
        settings.weekly = request.weekly
        settings.monthly = request.monthly
        settings.daily_send_time = request.daily_send_time
        settings.workflow_id = request.workflow_id
        for line in describe_changes(before, settings):
            record_change(
                settings,
                by_user_id=membership.user.id,
                by=_who(membership),
                change=line,
            )

    settings, _ = await service.change_settings(membership.organization_id, change)
    return await _response(membership, settings)


@router.post("/recipients", response_model=AddRecipientResponse)
async def add_email_report_recipient(
    request: AddRecipientRequest, membership: ReportsScheduler
):
    """Add an address. The member's own verified sign-in address starts
    straight away; any other address is sent a confirmation link and gets
    nothing until it is used."""
    now = datetime.now(UTC)
    own = service.own_verified_email(membership.user)

    def change(settings: EmailReportSettings):
        recipient = add_recipient(
            settings,
            address=str(request.email),
            by_user_id=membership.user.id,
            own_verified_email=own,
            now=now,
        )
        record_change(
            settings,
            by_user_id=membership.user.id,
            by=_who(membership),
            change=f"added {recipient.email} ({recipient.status})",
            now=now,
        )
        return recipient

    try:
        settings, recipient = await service.change_settings(
            membership.organization_id, change
        )
    except RecipientError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    sent = True
    if recipient.status == "pending":
        sent = await service.send_confirmation(
            membership.organization_id, recipient, added_by=_who(membership)
        )
    return AddRecipientResponse(
        recipient=_view(recipient),
        confirmation_sent=sent,
        settings=await _response(membership, settings),
    )


@router.post(
    "/recipients/{recipient_id}/resend", response_model=EmailReportSettingsResponse
)
async def resend_email_report_confirmation(
    recipient_id: str, membership: ReportsScheduler
):
    """A fresh confirmation link; the earlier one stops working."""
    now = datetime.now(UTC)
    try:
        settings, recipient = await service.change_settings(
            membership.organization_id,
            lambda s: refresh_confirmation(s, recipient_id, now),
        )
    except RecipientError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if not await service.send_confirmation(
        membership.organization_id, recipient, added_by=_who(membership)
    ):
        raise HTTPException(
            status_code=503, detail="Couldn't send the email just now. Try again later."
        )
    return await _response(membership, settings)


@router.delete("/recipients/{recipient_id}", response_model=EmailReportSettingsResponse)
async def remove_email_report_recipient(
    recipient_id: str, membership: ReportsScheduler
):
    def change(settings: EmailReportSettings):
        removed = remove_recipient(settings, recipient_id)
        if removed is not None:
            record_change(
                settings,
                by_user_id=membership.user.id,
                by=_who(membership),
                change=f"removed {removed.email}",
            )
        return removed

    settings, _ = await service.change_settings(membership.organization_id, change)
    return await _response(membership, settings)


@router.get(
    "/preview",
    response_class=HTMLResponse,
    responses={200: {"content": {"text/html": {"schema": {"type": "string"}}}}},
)
async def preview_email_report(
    membership: ReportsReader,
    frequency: Annotated[Frequency, Query()] = Frequency.DAILY,
):
    """The email as it would look now, from real calls: today so far for
    daily, the last full week or month otherwise."""
    report = await service.preview_report(
        membership.organization_id,
        frequency,
        show_credit=membership.can(Permission.BILLING_READ),
    )
    html = render.render_html(
        report,
        to=membership.user.email or "you",
        links=service.member_links("This is a preview. Nothing has been sent."),
    )
    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control": "no-store",
            # Shown in a sandboxed frame; it has no scripts of its own.
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors *",
        },
    )


@router.post("/test", response_model=TestReportResponse)
async def send_test_email_report(request: TestReportRequest, membership: ReportsReader):
    """Send this period's report to the member asking, and nobody else."""
    to = membership.user.email
    if not to:
        raise HTTPException(
            status_code=422, detail="Your account has no email address."
        )
    if not _delivers():
        raise HTTPException(
            status_code=503, detail="Email isn't set up on this server yet."
        )
    error = await service.send_test(
        membership.organization_id,
        request.frequency,
        user_id=membership.user.id,
        to=to,
        show_credit=membership.can(Permission.BILLING_READ),
    )
    if error:
        raise HTTPException(status_code=429 if "hour" in error else 503, detail=error)
    return TestReportResponse(sent_to=to)


@public_router.post("/confirm/{token}", response_model=LinkResult)
async def confirm_email_report_recipient(token: str):
    """Use the link from a confirmation email (works once, for 48 hours)."""
    return LinkResult(**await service.confirm_from_link(token))


@public_router.post("/unsubscribe/{token}", response_model=LinkResult)
async def unsubscribe_email_report_recipient(token: str):
    """The Unsubscribe link in every report, and the one-click
    List-Unsubscribe target (RFC 8058: a POST, its body ignored)."""
    return LinkResult(**await service.unsubscribe_from_link(token))
