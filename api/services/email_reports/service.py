"""Emailed reports: settings changes, confirmation links, unsubscribing,
previews and tests, and the scheduled send.

Idempotency of the scheduled send: before anything is sent, the period is
claimed in the workspace's ``EMAIL_REPORTS_SENT`` row under a row lock (see
``EmailReportClient.update_configuration_locked``). The claim records the
period's key; a second worker, a retried job or a restart then finds the key
already there and sends nothing. A send that fails half-way is logged, not
retried, so nobody gets the same report twice.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger

from api.constants import BACKEND_API_ENDPOINT, OSS_JWT_SECRET, UI_APP_URL
from api.db import db_client
from api.services.auth.permissions import Permission, has_permissions
from api.services.email import get_email_sender
from api.services.email.base import (
    EmailDeliveryError,
    EmailFailure,
    EmailMessage,
    EmailSender,
)
from api.services.email_reports import render, tokens
from api.services.email_reports.content import Report, load_report
from api.services.email_reports.periods import (
    DEFAULT_DAILY_SEND_TIME,
    GRACE,
    Frequency,
    Period,
    due_to_send,
    latest_due,
    parse_clock,
    preview_period,
)
from api.services.email_reports.settings import (
    SENT_KEY,
    SETTINGS_KEY,
    EmailReportSettings,
    ReportRecipient,
    parse_settings,
    record_change,
)

CONFIRM_HOURS = int(tokens.CONFIRM_TTL.total_seconds() // 3600)
# Confirmation emails per workspace per day, so the form can't be used to
# mail strangers in bulk.
CONFIRMATIONS_PER_DAY = 20
TESTS_PER_HOUR = 6
_RETRY_DELAY = 2.0


def _ui(path: str) -> str:
    return f"{UI_APP_URL.rstrip('/')}{path}"


def _api(path: str) -> str:
    return f"{BACKEND_API_ENDPOINT.rstrip('/')}/api/v1{path}"


def business_name(name: str | None) -> str:
    return (name or "").strip() or "Your business"


async def resolve_business_name(
    organization_id: int,
    organization_name: str | None,
    workflow_id: int | None = None,
) -> str:
    """The workspace's name; when it has none, the business name its agent
    was given (the ``business_name`` fact), if the agents agree on one."""
    if (organization_name or "").strip():
        return organization_name.strip()
    if workflow_id is not None:
        ids = [workflow_id]
    else:
        ids = [a["id"] for a in await db_client.get_dashboard_agents(organization_id)]
    names: set[str] = set()
    for agent_id in ids[:10]:
        workflow = await db_client.get_workflow(
            agent_id, organization_id=organization_id
        )
        facts = getattr(workflow, "template_context_variables", None) or {}
        value = facts.get("business_name") if isinstance(facts, dict) else None
        if isinstance(value, str) and value.strip():
            names.add(value.strip())
    return names.pop() if len(names) == 1 else business_name(None)


# ---------------------------------------------------------------- settings


async def load_settings(organization_id: int) -> EmailReportSettings:
    row = await db_client.get_configuration(organization_id, SETTINGS_KEY)
    return parse_settings(row.value if row is not None else None, organization_id)


async def change_settings(
    organization_id: int, change: Callable[[EmailReportSettings], Any]
) -> tuple[EmailReportSettings, Any]:
    """Apply ``change`` to the stored settings under the row lock. If it
    raises, nothing is saved. Returns the saved settings and its result."""

    def mutate(value: dict) -> tuple[dict, tuple[EmailReportSettings, Any]]:
        settings = parse_settings(value, organization_id)
        result = change(settings)
        # Validate again: a change must leave a valid row behind.
        settings = EmailReportSettings.model_validate(settings.model_dump())
        return settings.model_dump(mode="json"), (settings, result)

    return await db_client.update_configuration_locked(
        organization_id, SETTINGS_KEY, mutate
    )


async def last_sent(organization_id: int) -> dict[str, str]:
    row = await db_client.get_configuration(organization_id, SENT_KEY)
    value = row.value if row is not None and isinstance(row.value, dict) else {}
    return {
        f.value: value[f.value]
        for f in Frequency
        if isinstance(value.get(f.value), str)
    }


def send_time(settings: EmailReportSettings, frequency: Frequency) -> time:
    if frequency != Frequency.DAILY:
        return time(8, 0)
    try:
        return parse_clock(settings.daily_send_time)
    except ValueError:
        return DEFAULT_DAILY_SEND_TIME


async def report_zone(
    organization_id: int, workflow_id: int | None
) -> tuple[ZoneInfo, list[dict[str, Any]]]:
    """The zone the dashboard would use, and the workspace's agents."""
    from api.services.dashboard.service import resolve_timezone

    agents = await db_client.get_dashboard_agents(organization_id)
    tz = await resolve_timezone(organization_id, None, workflow_id, agents)
    return tz, agents


# ------------------------------------------------------------- recipients


def own_verified_email(user) -> str | None:
    """The member's sign-in address, when it was verified at sign-up (local
    accounts record it; Stack Auth only hands over verified addresses)."""
    from api.constants import AUTH_PROVIDER

    if not user.email:
        return None
    if AUTH_PROVIDER == "local" and user.email_verified_at is None:
        return None
    return user.email


def confirm_link(organization_id: int, recipient: ReportRecipient) -> str:
    assert recipient.confirm_nonce is not None
    token = tokens.confirm_token(
        organization_id=organization_id,
        recipient_id=recipient.id,
        address=recipient.email,
        nonce=recipient.confirm_nonce,
        secret=OSS_JWT_SECRET,
    )
    return _ui(f"/reports/confirm/{token}")


async def _within(key: str, limit: int, window) -> bool:
    from api.services.rate_limit import get_rate_limiter

    return await get_rate_limiter().allow(key, limit=limit, window=window)


async def send_confirmation(
    organization_id: int,
    recipient: ReportRecipient,
    *,
    added_by: str | None,
    sender: EmailSender | None = None,
) -> bool:
    """Email the confirmation link. False when it couldn't go (no email
    service, the daily cap, or the provider refused)."""
    from datetime import timedelta

    if not await _within(
        f"email-report-confirm:{organization_id}:{datetime.now(UTC).date()}",
        CONFIRMATIONS_PER_DAY,
        timedelta(days=1),
    ):
        logger.warning(
            f"[email-reports] organization {organization_id} hit the daily "
            "confirmation email limit"
        )
        return False
    organization = await db_client.get_organization_by_id(organization_id)
    message = render.confirmation_message(
        to=recipient.email,
        business_name=await resolve_business_name(
            organization_id, getattr(organization, "name", None)
        ),
        added_by=added_by,
        confirm_url=confirm_link(organization_id, recipient),
        hours=CONFIRM_HOURS,
    )
    return await _deliver(sender or get_email_sender(), message) is None


def _matcher(claim: tokens.RecipientClaim):
    def matches(recipient: ReportRecipient, nonce: str | None) -> bool:
        if not hmac.compare_digest(
            claim.email_hash, tokens.email_hash(recipient.email)
        ):
            return False
        if nonce is None:
            return True
        return claim.nonce is not None and hmac.compare_digest(claim.nonce, nonce)

    return matches


async def confirm_from_link(token: str) -> dict[str, Any]:
    from api.services.email_reports.settings import confirm_recipient

    claim = tokens.read_confirm_token(token, OSS_JWT_SECRET)
    if claim is None:
        return {"status": "invalid", "business_name": None}
    now = datetime.now(UTC)

    def change(settings: EmailReportSettings):
        outcome = confirm_recipient(
            settings, claim.recipient_id, email_matches=_matcher(claim), now=now
        )
        if outcome == "confirmed":
            recipient = settings.find(claim.recipient_id)
            record_change(
                settings,
                by_user_id=None,
                by=recipient.email if recipient else None,
                change="confirmed their address",
                now=now,
            )
        return outcome

    organization = await db_client.get_organization_by_id(claim.organization_id)
    if organization is None or getattr(organization, "erased_at", None):
        return {"status": "invalid", "business_name": None}
    _, outcome = await change_settings(claim.organization_id, change)
    return {
        "status": outcome,
        "business_name": await resolve_business_name(
            claim.organization_id, organization.name
        )
        if outcome != "invalid"
        else None,
    }


async def unsubscribe_from_link(token: str) -> dict[str, Any]:
    claim = tokens.read_unsubscribe_token(token, OSS_JWT_SECRET)
    if claim is None:
        return {"status": "invalid", "business_name": None}
    organization = await db_client.get_organization_by_id(claim.organization_id)
    if organization is None:
        return {"status": "invalid", "business_name": None}
    matches = _matcher(claim)

    def change(settings: EmailReportSettings):
        recipient = settings.find(claim.recipient_id)
        if recipient is None:
            return "already"
        if not matches(recipient, None):
            return "invalid"
        settings.recipients = [r for r in settings.recipients if r.id != recipient.id]
        record_change(
            settings, by_user_id=None, by=recipient.email, change="unsubscribed"
        )
        return "removed"

    _, outcome = await change_settings(claim.organization_id, change)
    return {
        "status": outcome,
        "business_name": await resolve_business_name(
            claim.organization_id, organization.name
        )
        if outcome != "invalid"
        else None,
    }


# ----------------------------------------------------------------- sending


async def _deliver(sender: EmailSender, message: EmailMessage) -> str | None:
    """Send once, once more after a transient failure; None when sent."""
    for attempt in (1, 2):
        try:
            await sender.send(message)
            return None
        except EmailDeliveryError as exc:
            logger.warning(f"[email-reports] attempt {attempt} failed: {exc.failure}")
            if attempt == 2 or exc.failure == EmailFailure.FINAL:
                return f"{type(exc).__name__}: {exc.failure}"
            await asyncio.sleep(_RETRY_DELAY)
        except Exception as exc:  # noqa: BLE001 - one bad send must not stop the rest
            return type(exc).__name__
    return "not sent"


def recipient_links(organization_id: int, recipient: ReportRecipient) -> render.Links:
    token = tokens.unsubscribe_token(
        organization_id=organization_id,
        recipient_id=recipient.id,
        address=recipient.email,
        secret=OSS_JWT_SECRET,
    )
    return render.Links(
        dashboard=_ui("/overview"),
        follow_ups=_ui("/follow-ups"),
        manage=_ui("/settings/reports"),
        unsubscribe=_ui(f"/reports/unsubscribe/{token}"),
        one_click=_api(f"/public/email-reports/unsubscribe/{token}"),
        billing=_ui("/billing"),
    )


def member_links(why: str) -> render.Links:
    """For a preview or a test sent to a member: no unsubscribe token, the
    footer link goes to the settings screen instead."""
    return render.Links(
        dashboard=_ui("/overview"),
        follow_ups=_ui("/follow-ups"),
        manage=_ui("/settings/reports"),
        unsubscribe=_ui("/settings/reports"),
        billing=_ui("/billing"),
        why=why,
    )


async def billing_readers(organization_id: int) -> set[str]:
    """Addresses of members whose role may see billing (credit is left out
    for everyone else, outside addresses included)."""
    members = await db_client.list_organization_members(organization_id)
    return {
        m.email.strip().casefold()
        for m in members
        if m.email and has_permissions(m.role, Permission.BILLING_READ)
    }


def _key(organization_id: int, period: Period, address: str) -> str:
    digest = hashlib.sha256(address.casefold().encode()).hexdigest()[:16]
    return f"email-report-{organization_id}-{period.frequency}-{period.key}-{digest}"


async def build(
    organization_id: int,
    organization_name: str | None,
    settings: EmailReportSettings,
    period: Period,
    tz: ZoneInfo,
    agents: list[dict[str, Any]],
    now: datetime | None = None,
) -> Report:
    return await load_report(
        organization_id=organization_id,
        business_name=await resolve_business_name(
            organization_id, organization_name, settings.workflow_id
        ),
        workflow_id=settings.workflow_id,
        period=period,
        tz=tz,
        agents=agents,
        now=now,
    )


async def send_report(
    organization_id: int,
    organization_name: str | None,
    settings: EmailReportSettings,
    period: Period,
    tz: ZoneInfo,
    agents: list[dict[str, Any]],
    sender: EmailSender,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Send one claimed report to every confirmed recipient. Returns
    ``(sent, failed)``."""
    report = await build(
        organization_id, organization_name, settings, period, tz, agents, now
    )
    readers = await billing_readers(organization_id)
    sent = failed = 0
    for recipient in settings.active_recipients():
        shown = (
            report
            if recipient.email.strip().casefold() in readers
            else replace(report, credit=None)
        )
        message = render.report_message(
            shown,
            to=recipient.email,
            links=recipient_links(organization_id, recipient),
            idempotency_key=_key(organization_id, period, recipient.email),
        )
        error = await _deliver(sender, message)
        if error is None:
            sent += 1
        else:
            failed += 1
            logger.warning(
                f"[email-reports] {period.frequency} {period.key} for organization "
                f"{organization_id} not delivered to one recipient: {error}"
            )
    return sent, failed


async def claim_period(
    organization_id: int,
    frequency: Frequency,
    now: datetime,
    tz: ZoneInfo,
    clock: time,
) -> Period | None:
    """Record that ``frequency``'s due period is being sent, under the row
    lock; None when it is not due or another worker already claimed it."""

    def mutate(value: dict):
        last = value.get(frequency.value)
        period = due_to_send(
            frequency, now, tz, clock, last if isinstance(last, str) else None
        )
        if period is None:
            return None, None
        value[frequency.value] = period.key
        value[f"{frequency.value}_sent_at"] = now.isoformat()
        return value, period

    return await db_client.update_configuration_locked(
        organization_id, SENT_KEY, mutate
    )


async def send_due_reports(
    now: datetime | None = None,
    sender_factory: Callable[[], EmailSender] = get_email_sender,
) -> dict[str, int]:
    """The cron's work: every open workspace's reports whose send time has
    passed and that weren't sent yet."""
    now = now or datetime.now(UTC)
    totals = {"reports": 0, "emails": 0, "failed": 0}
    try:
        sender = sender_factory()
    except Exception:  # noqa: BLE001 - a misconfigured provider sends nothing
        logger.exception("[email-reports] email service unavailable")
        return totals
    if not sender.delivers:
        # Not claimed either: once email is set up, due reports still go.
        return totals
    for organization_id, name, value in await db_client.list_report_configurations(
        SETTINGS_KEY
    ):
        settings = parse_settings(value, organization_id)
        wanted = [f for f in Frequency if settings.enabled(f)]
        if not wanted or not settings.active_recipients():
            continue
        try:
            tz, agents = await report_zone(organization_id, settings.workflow_id)
            for frequency in wanted:
                clock = send_time(settings, frequency)
                # Cheap check first; the claim below is the one that counts.
                due = latest_due(frequency, now, tz, clock)
                if now - due.send_at > GRACE[frequency]:
                    continue
                period = await claim_period(organization_id, frequency, now, tz, clock)
                if period is None:
                    continue
                sent, failed = await send_report(
                    organization_id, name, settings, period, tz, agents, sender, now
                )
                totals["reports"] += 1
                totals["emails"] += sent
                totals["failed"] += failed
                logger.info(
                    f"[email-reports] {frequency} {period.key} for organization "
                    f"{organization_id}: {sent} sent, {failed} failed"
                )
        except Exception:  # noqa: BLE001 - one workspace must not stop the rest
            logger.exception(f"[email-reports] organization {organization_id} failed")
    return totals


# ------------------------------------------------------- preview and test


async def preview_report(
    organization_id: int,
    frequency: Frequency,
    *,
    show_credit: bool,
    now: datetime | None = None,
) -> Report:
    now = now or datetime.now(UTC)
    settings = await load_settings(organization_id)
    tz, agents = await report_zone(organization_id, settings.workflow_id)
    period = preview_period(frequency, now, tz, send_time(settings, frequency))
    organization = await db_client.get_organization_by_id(organization_id)
    report = await build(
        organization_id,
        getattr(organization, "name", None),
        settings,
        period,
        tz,
        agents,
        now,
    )
    return report if show_credit else replace(report, credit=None)


async def send_test(
    organization_id: int,
    frequency: Frequency,
    *,
    user_id: int,
    to: str,
    show_credit: bool,
    sender: EmailSender | None = None,
) -> str | None:
    """Send this period's report to the member asking, and nobody else.
    None when sent, else why not."""
    from datetime import timedelta

    if not await _within(
        f"email-report-test:{user_id}", TESTS_PER_HOUR, timedelta(hours=1)
    ):
        return "You've sent a few tests already. Try again in an hour."
    report = await preview_report(organization_id, frequency, show_credit=show_credit)
    message = render.report_message(
        report,
        to=to,
        links=member_links(
            "This is a test you asked for, sent only to you. Scheduled reports go "
            "to the addresses on the Reports by email screen."
        ),
    )
    message = replace(message, subject=f"Test: {message.subject}")
    error = await _deliver(sender or get_email_sender(), message)
    return (
        None
        if error is None
        else "The email service didn't accept it. Try again later."
    )
