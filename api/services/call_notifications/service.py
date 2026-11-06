"""After a call: email the business, and text the caller their booking.

Runs from the post-call jobs (``api/tasks/workflow_completion.py`` and the
standalone integrations job for calls that never reached the agent). Best
effort throughout: nothing here may fail the job that calls it.

At most once: each channel is claimed in ``call_notifications`` before it
sends, so a retried job, or both jobs running for the same run, never send
twice. Each email also carries an idempotency key (Resend drops a repeat it
already accepted), so retrying one recipient after an unclear failure is
safe.

Bounded: the business's recipients are emailed concurrently under one
overall timeout, and each one is retried by failure kind (see
``api.services.email.base.EmailFailure``), so a slow provider cannot hold
the post-call job for long.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, assert_never
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger

from api.constants import CALL_SUMMARY_DAILY_LIMIT, UI_APP_URL
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
    is_outbound_phone_call,
    is_phone_call,
)
from api.services.call_notifications.phone import textable_number
from api.services.call_notifications.settings import (
    email_recipients,
    load_notification_settings,
    member_recipients,
)
from api.services.email import get_email_sender
from api.services.email.base import (
    EmailDeliveryError,
    EmailFailure,
    EmailMessage,
    EmailSender,
)
from api.services.rate_limit import RateLimiter, get_rate_limiter
from api.services.sms import get_sms_sender
from api.services.sms.base import SmsMessage, SmsSender

EMAIL = "email"
SMS = "sms"
DEFAULT_TIMEZONE = "Europe/Dublin"
# Waits before the second and third attempt at one recipient. A transient
# failure (rate limit, dropped connection) may use both, a provider error
# (5xx) only the first, a final one (bad key, refused address) neither.
DEFAULT_RETRY_DELAYS_SECONDS = (2.0, 8.0)
# Bounds all of one call's emails, retries included, so a slow provider
# cannot hold the post-call job (and the post-call marker) for long.
DEFAULT_SEND_TIMEOUT_SECONDS = 45.0
# The daily count is a backstop: a slow Redis must not hold the send up.
LIMITER_TIMEOUT_SECONDS = 2.0
# What the outbound events may email about: an unanswered outbound call is
# not a missed call for the business.
_OUTBOUND_EVENTS = frozenset({CallEvent.BOOKING_MADE, CallEvent.MESSAGE_TAKEN})


@dataclass(frozen=True, slots=True)
class EmailDelivery:
    """How the business's emails are sent: retries, overall timeout and the
    per-organization daily cap (``CALL_SUMMARY_DAILY_LIMIT``)."""

    rate_limiter: RateLimiter | None = None
    daily_limit: int = CALL_SUMMARY_DAILY_LIMIT
    retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS_SECONDS
    send_timeout: float = DEFAULT_SEND_TIMEOUT_SECONDS
    limiter_timeout: float = LIMITER_TIMEOUT_SECONDS
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


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


def _idempotency_key(run_id: int, channel: str, address: str) -> str:
    """One key per run, channel and recipient. Hashed: the address would make
    the key long and put it in request headers."""
    digest = hashlib.sha256(address.casefold().encode()).hexdigest()[:16]
    return f"call-notice-{run_id}-{channel}-{digest}"


def _retries_for(failure: EmailFailure, delays: Sequence[float]) -> int:
    match failure:
        case EmailFailure.TRANSIENT:
            return len(delays)
        case EmailFailure.PROVIDER_ERROR:
            return min(1, len(delays))
        case EmailFailure.FINAL:
            return 0
        case _:
            assert_never(failure)


async def _deliver(
    sender: EmailSender, message: EmailMessage, delivery: EmailDelivery
) -> str | None:
    """Send one message, retrying by failure kind; None when it went, else
    the last error."""
    attempt = 1
    while True:
        try:
            await sender.send(message)
            return None
        except EmailDeliveryError as exc:
            # The error text can echo addresses: only its kind is logged here.
            logger.warning(
                f"[notifications] email attempt {attempt} failed: {exc.failure}"
            )
            if attempt > _retries_for(exc.failure, delivery.retry_delays):
                return f"{type(exc).__name__}: {exc}"
            await delivery.sleep(delivery.retry_delays[attempt - 1])
            attempt += 1
        except Exception as exc:  # noqa: BLE001 - one bad send must not stop the rest
            return f"{type(exc).__name__}: {exc}"


async def _send_all(
    sender: EmailSender, messages: Sequence[EmailMessage], delivery: EmailDelivery
) -> list[str]:
    """Send concurrently under ``delivery.send_timeout``; the errors of the
    messages that did not go, one each.

    Every send task is stopped before this returns or raises, so none
    outlives a cancelled job (ARQ timeout, worker shutdown). An SMTP send
    already in its worker thread may still finish; the claim keeps that from
    becoming a duplicate.
    """
    if not messages:
        return []
    tasks = [asyncio.create_task(_deliver(sender, m, delivery)) for m in messages]
    try:
        _, pending = await asyncio.wait(tasks, timeout=delivery.send_timeout)
        if pending:
            logger.warning(
                f"[notifications] {len(pending)} email(s) still sending after "
                f"{delivery.send_timeout:g}s were stopped"
            )
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    failures: list[str] = []
    for task in tasks:
        if task.cancelled():
            failures.append(f"TimeoutError: not sent within {delivery.send_timeout:g}s")
        elif (error := task.exception()) is not None:
            failures.append(f"{type(error).__name__}: {error}")
        elif (failure := task.result()) is not None:
            failures.append(failure)
    return failures


async def _within_daily_limit(organization_id: int, delivery: EmailDelivery) -> bool:
    """Counts this call against the organization's emails for the UTC day.
    Fails open: no limiter, a Redis error or a slow Redis allow the send."""
    limiter = delivery.rate_limiter
    if limiter is None:
        return True
    day = datetime.now(UTC).date().isoformat()
    try:
        async with asyncio.timeout(delivery.limiter_timeout):
            allowed = await limiter.allow(
                f"call-notifications:{organization_id}:{day}",
                limit=delivery.daily_limit,
                window=timedelta(days=1),
            )
    except TimeoutError:
        logger.warning("[notifications] daily email limit unavailable; sending")
        return True
    if not allowed:
        logger.warning(
            f"[notifications] organization {organization_id} reached its daily "
            f"limit of {delivery.daily_limit} call emails"
        )
    return allowed


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
    # On an outbound call the business's line is the caller.
    inbound = is_phone_call(run.mode, run.call_type)
    business_key, contact_key = (
        ("called_number", "caller_number")
        if inbound
        else ("caller_number", "called_number")
    )
    return CallFacts(
        business_name=business_name,
        business_number=_text(initial.get(business_key)) or None,
        caller_number=_text(initial.get(contact_key)) or None,
        called_at=created.astimezone(zone),
        call_url=f"{UI_APP_URL.rstrip('/')}/workflow/{run.workflow_id}/run/{run.id}",
        gathered_context=run.gathered_context or {},
        inbound=inbound,
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
    delivery: EmailDelivery,
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
    # Counted after the claim, so a duplicate job uses none of the allowance.
    if sender.delivers and not await _within_daily_limit(organization_id, delivery):
        await db.finish_call_notification(
            run_id, EMAIL, status="limited", recipient_count=0
        )
        return

    messages: list[EmailMessage] = []
    for address in recipients:
        message = business_email(to=address, outcome=outcome, facts=facts)
        if message is None:
            break
        key = _idempotency_key(run_id, EMAIL, address)
        messages.append(replace(message, idempotency_key=key))
    failures = await _send_all(sender, messages, delivery)
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
    # Bookings made or moved on this call; a call that only cancelled has
    # nothing to confirm.
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
    delivery: EmailDelivery | None = None,
) -> None:
    """Email the business and text the caller about one finished call, as the
    organization's settings say. Never raises.

    Inbound phone calls get every notification; outbound phone calls only
    email the business about a booking change or a message.
    """
    try:
        run = await db.get_workflow_run_by_id(workflow_run_id)
        if run is None:
            return
        inbound = is_phone_call(run.mode, run.call_type)
        if not inbound and not is_outbound_phone_call(run.mode, run.call_type):
            return
        outcome = classify_call(
            gathered_context=run.gathered_context,
            logs=run.logs,
            usage_info=run.usage_info,
        )
        if outcome.event is None:
            return
        if not inbound and outcome.event not in _OUTBOUND_EVENTS:
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

    if delivery is None:
        delivery = EmailDelivery(rate_limiter=_sender(get_rate_limiter, "Rate limit"))
    email_sender = _sender(email_sender_factory, "Email")
    if email_sender is not None:
        try:
            await _email_business(
                run.id,
                organization_id,
                outcome,
                facts,
                settings,
                email_sender,
                delivery,
                db,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[notifications] run {run.id}: email step failed: {exc}")

    if (
        inbound
        and outcome.event is CallEvent.BOOKING_MADE
        and settings.text_caller_booking_confirmation
    ):
        sms_sender = _sender(sms_sender_factory, "SMS")
        if sms_sender is not None:
            try:
                await _text_caller(run, outcome, facts, settings, sms_sender, db)
            except Exception as exc:  # noqa: BLE001
                logger.error(f"[notifications] run {run.id}: text step failed: {exc}")
