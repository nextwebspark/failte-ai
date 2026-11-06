"""After a call: email the business, and text the caller their booking.

Runs from the post-call jobs (``api/tasks/workflow_completion.py`` and the
standalone integrations job for calls that never reached the agent). Best
effort throughout: nothing here may fail the job that calls it.

At most once: each channel is claimed in ``call_notifications`` before it
sends, so a retried job, or both jobs running for the same run, never send
twice.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger

from api.constants import UI_APP_URL
from api.db import db_client
from api.schemas.call_notifications import CallNotificationSettings
from api.services.call_notifications.messages import (
    CallFacts,
    booking_confirmation_text,
    business_email,
)
from api.services.call_notifications.outcome import (
    CallEvent,
    CallOutcome,
    classify_call,
    is_phone_call,
)
from api.services.call_notifications.phone import textable_number
from api.services.call_notifications.settings import (
    email_recipients,
    load_notification_settings,
    member_recipients,
)
from api.services.email import get_email_sender
from api.services.email.base import EmailSender
from api.services.sms import get_sms_sender
from api.services.sms.base import SmsMessage, SmsSender

EMAIL = "email"
SMS = "sms"
DEFAULT_TIMEZONE = "Europe/Dublin"


_EMAIL_ADDRESS = re.compile(r"[^\s@'\"<>]+@[^\s@'\"<>]+")
_PHONE_NUMBER = re.compile(r"\+?\d[\d ]{5,}\d")


def _redacted(error: str) -> str:
    """A provider error for the bookkeeping row, without the addresses or
    numbers providers like to quote back ("The 'To' number +353... is not
    valid"): the row is meant to hold no personal data."""
    return _PHONE_NUMBER.sub("[number]", _EMAIL_ADDRESS.sub("[address]", error))


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _email_wanted(settings: CallNotificationSettings, event: CallEvent) -> bool:
    if not settings.email_enabled:
        return False
    return {
        CallEvent.BOOKING_MADE: settings.email_on_booking,
        CallEvent.MESSAGE_TAKEN: settings.email_on_message,
        CallEvent.MISSED_CALL: settings.email_on_missed_call,
    }[event]


def _zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


async def _organization_timezone(organization_id: int, db) -> str | None:
    # Imported here: organization_preferences pulls in the call-events stack.
    from api.services.organization_preferences import get_organization_preferences

    try:
        return (await get_organization_preferences(organization_id, db=db)).timezone
    except Exception:  # noqa: BLE001 - the default zone is a fine answer
        return None


async def _call_facts(run, organization_id: int, db) -> CallFacts:
    initial: Mapping[str, Any] = run.initial_context or {}
    template: Mapping[str, Any] = (
        getattr(run.workflow, "template_context_variables", None) or {}
    )
    business_name = _text(initial.get("business_name")) or _text(
        template.get("business_name")
    )
    if not business_name:
        organization = await db.get_organization_by_id(organization_id)
        business_name = _text(getattr(organization, "name", None)) or "Your business"
    created = run.created_at or datetime.now(UTC)
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    zone = _zone(await _organization_timezone(organization_id, db))
    return CallFacts(
        business_name=business_name,
        business_number=_text(initial.get("called_number")) or None,
        caller_number=_text(initial.get("caller_number")) or None,
        called_at=created.astimezone(zone),
        call_url=f"{UI_APP_URL.rstrip('/')}/workflow/{run.workflow_id}/run/{run.id}",
        gathered_context=run.gathered_context or {},
    )


def _sender(factory: Callable[[], Any], what: str) -> Any | None:
    try:
        return factory()
    except Exception as exc:  # noqa: BLE001 - misconfiguration must not fail the job
        logger.error(f"[notifications] {what} provider is misconfigured: {exc}")
        return None


async def _email_business(
    run_id: int,
    organization_id: int,
    outcome: CallOutcome,
    facts: CallFacts,
    settings: CallNotificationSettings,
    sender: EmailSender,
    db,
) -> None:
    assert outcome.event is not None
    if not _email_wanted(settings, outcome.event):
        return
    recipients = email_recipients(
        settings,
        await member_recipients(organization_id, db) if settings.email_members else [],
    )
    if not recipients:
        logger.warning(
            f"[notifications] run {run_id}: no one to email about "
            f"{outcome.event.value} (organization {organization_id})"
        )
        return
    if not await db.claim_call_notification(run_id, EMAIL, outcome.event.value):
        logger.info(f"[notifications] run {run_id}: email already handled")
        return

    failures: list[str] = []
    for address in recipients:
        message = business_email(to=address, outcome=outcome, facts=facts)
        if message is None:
            break
        try:
            await sender.send(message)
        except Exception as exc:  # noqa: BLE001 - one bad address must not stop the rest
            failures.append(f"{type(exc).__name__}: {exc}")
    if not failures:
        status = "sent" if sender.delivers else "logged"
    else:
        status = "failed" if len(failures) == len(recipients) else "partial"
        logger.warning(
            f"[notifications] run {run_id}: {len(failures)} of {len(recipients)} "
            f"email(s) failed: {_redacted(failures[0])}"
        )
    await db.finish_call_notification(
        run_id,
        EMAIL,
        status=status,
        recipient_count=len(recipients) - len(failures),
        error=_redacted(failures[0]) if failures else None,
    )
    logger.info(
        f"[notifications] run {run_id}: {outcome.event.value} email {status} "
        f"to {len(recipients) - len(failures)} recipient(s)"
    )


async def _text_caller(
    run,
    outcome: CallOutcome,
    facts: CallFacts,
    settings: CallNotificationSettings,
    sender: SmsSender,
    db,
) -> None:
    if outcome.event is not CallEvent.BOOKING_MADE or not outcome.bookings:
        return
    if not settings.text_caller_booking_confirmation:
        return
    booking = outcome.bookings[-1]
    gathered = run.gathered_context or {}
    to = textable_number(
        facts.caller_number, booking.caller_phone, gathered.get("callback_number")
    )
    if to is None:
        logger.info(
            f"[notifications] run {run.id}: no mobile number to text the "
            "booking confirmation to"
        )
        return
    if not await db.claim_call_notification(run.id, SMS, outcome.event.value):
        logger.info(f"[notifications] run {run.id}: text already handled")
        return
    body = booking_confirmation_text(
        booking=booking,
        business_name=facts.business_name,
        business_number=facts.business_number,
    )
    try:
        await sender.send(SmsMessage(to=to, body=body))
    except Exception as exc:  # noqa: BLE001 - recorded, never raised
        logger.warning(
            f"[notifications] run {run.id}: text failed: {_redacted(str(exc))}"
        )
        await db.finish_call_notification(
            run.id,
            SMS,
            status="failed",
            recipient_count=0,
            error=_redacted(f"{type(exc).__name__}: {exc}"),
        )
        return
    status = "sent" if sender.delivers else "logged"
    await db.finish_call_notification(run.id, SMS, status=status, recipient_count=1)
    logger.info(f"[notifications] run {run.id}: booking confirmation text {status}")


async def send_call_notifications(
    workflow_run_id: int,
    *,
    db=db_client,
    email_sender_factory: Callable[[], EmailSender] = get_email_sender,
    sms_sender_factory: Callable[[], SmsSender] = get_sms_sender,
) -> None:
    """Email the business and text the caller about one finished call, as the
    organization's settings say. Never raises."""
    try:
        run = await db.get_workflow_run_by_id(workflow_run_id)
        if run is None or not is_phone_call(run.mode, run.call_type):
            return
        outcome = classify_call(
            gathered_context=run.gathered_context,
            logs=run.logs,
            usage_info=run.usage_info,
        )
        if outcome.event is None:
            return
        organization_id = run.workflow.organization_id
        settings = await load_notification_settings(organization_id, db)
        facts = await _call_facts(run, organization_id, db)
    except Exception as exc:  # noqa: BLE001 - never fail the post-call job
        logger.error(
            f"[notifications] could not read run {workflow_run_id}: "
            f"{type(exc).__name__}: {exc}"
        )
        return

    email_sender = _sender(email_sender_factory, "Email")
    if email_sender is not None:
        try:
            await _email_business(
                run.id, organization_id, outcome, facts, settings, email_sender, db
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[notifications] run {run.id}: email step failed: {exc}")

    if (
        outcome.event is CallEvent.BOOKING_MADE
        and settings.text_caller_booking_confirmation
    ):
        sms_sender = _sender(sms_sender_factory, "SMS")
        if sms_sender is not None:
            try:
                await _text_caller(run, outcome, facts, settings, sms_sender, db)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"[notifications] run {run.id}: text step failed: {exc}")
