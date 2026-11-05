"""Email the business what a finished call left for it.

Runs as the last step of the completion job, before the post-call marker that
call erasure waits for, so it is bounded: recipients are sent to concurrently
under one overall timeout.

Sending is at most once per run: the run is claimed before the first email
goes out, so a re-run job (worker restart, duplicate completion) never repeats
it, and a crash between the claim and the send loses that summary rather than
duplicating it. Each email also carries an idempotency key, so a provider
that saw an attempt that looked failed to us drops the retry.
"""

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, timedelta, tzinfo
from enum import StrEnum
from typing import assert_never
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger

from api.db.call_summary_client import CallSummaryRun
from api.enums import WORKFLOW_RUN_MODES_BY_CHANNEL, WorkflowRunChannel
from api.schemas.call_summary_email import CallSummaryEmailConfiguration
from api.services.call_summary.configuration import resolve_call_summary_email
from api.services.call_summary.ports import CallSummaryStore, TimezoneLookup
from api.services.call_summary.summary import (
    BookingAction,
    BookingChange,
    CallSummary,
    extract_call_summary,
)
from api.services.email.base import (
    EmailDeliveryError,
    EmailFailure,
    EmailMessage,
    EmailSender,
)
from api.services.email.templates import call_summary_message
from api.services.rate_limit import RateLimiter
from api.utils.clock import Clock

_PHONE_MODES = frozenset(
    WORKFLOW_RUN_MODES_BY_CHANNEL[WorkflowRunChannel.TELEPHONY.value]
)
# Waits before the second and third attempt at one recipient. A transient
# failure may use both, a provider error only the first (the idempotency key
# makes that retry safe), a final one neither.
DEFAULT_RETRY_DELAYS_SECONDS = (2.0, 8.0)
# Bounds the whole send, retries included, so a slow provider cannot hold the
# completion job (and with it the post-call marker) for long. Two 15s Resend
# timeouts plus the first delay fit inside it.
DEFAULT_SEND_TIMEOUT_SECONDS = 45.0
# The daily count is a backstop: a slow Redis must not hold the send up.
_LIMITER_TIMEOUT_SECONDS = 2.0
_TIME_FORMAT = "%a %d %b %Y, %H:%M %Z"


class CallSummaryOutcome(StrEnum):
    SENT = "sent"
    # Claimed, but no recipient could be reached.
    FAILED = "failed"
    ALREADY_SENT = "already_sent"
    DAILY_LIMIT_REACHED = "daily_limit_reached"
    RUN_NOT_FOUND = "run_not_found"
    TURNED_OFF = "turned_off"
    NOT_A_PHONE_CALL = "not_a_phone_call"
    NOT_COMPLETED = "not_completed"
    NOTHING_TO_REPORT = "nothing_to_report"
    # EMAIL_PROVIDER=none: nothing would leave the process.
    EMAIL_NOT_CONFIGURED = "email_not_configured"


def skip_reason(
    run: CallSummaryRun, setting: CallSummaryEmailConfiguration
) -> CallSummaryOutcome | None:
    """Why this run gets no summary regardless of what was said, or None.

    Only phone calls qualify. Web calls are mostly the owner testing the agent
    in the builder, and from the run alone they cannot be told apart from a
    website visitor's call; text chats have no caller to call back.
    """
    if not setting.enabled:
        return CallSummaryOutcome.TURNED_OFF
    if run.mode not in _PHONE_MODES:
        return CallSummaryOutcome.NOT_A_PHONE_CALL
    if not run.is_completed:
        return CallSummaryOutcome.NOT_COMPLETED
    return None


class CallSummaryNotifier:
    def __init__(
        self,
        *,
        store: CallSummaryStore,
        email_sender: EmailSender,
        clock: Clock,
        timezone_of: TimezoneLookup,
        rate_limiter: RateLimiter,
        daily_limit: int,
        app_url: str,
        retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS_SECONDS,
        send_timeout: float = DEFAULT_SEND_TIMEOUT_SECONDS,
        limiter_timeout: float = _LIMITER_TIMEOUT_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._store = store
        self._email = email_sender
        self._clock = clock
        self._timezone_of = timezone_of
        self._limiter = rate_limiter
        self._daily_limit = daily_limit
        self._app_url = app_url.rstrip("/")
        self._retry_delays = tuple(retry_delays)
        self._send_timeout = send_timeout
        self._limiter_timeout = limiter_timeout
        self._sleep = sleep

    async def notify(self, run_id: int) -> CallSummaryOutcome:
        outcome = await self._notify(run_id)
        # Counts and ids only: the summary and its addresses are personal data.
        logger.info("Call summary email for run {}: {}", run_id, outcome)
        return outcome

    async def _notify(self, run_id: int) -> CallSummaryOutcome:
        run = await self._store.get_call_summary_run(run_id)
        if run is None:
            return CallSummaryOutcome.RUN_NOT_FOUND
        setting = resolve_call_summary_email(run.workflow_configurations)
        skipped = skip_reason(run, setting)
        if skipped is not None:
            return skipped
        # The call's events are the largest part of the run: load them only
        # once a summary may be due.
        events = await self._store.get_call_summary_events(run_id)
        summary = extract_call_summary(run.gathered_context, events)
        if summary is None:
            return CallSummaryOutcome.NOTHING_TO_REPORT
        # The logging fallback would write the caller's details to the log.
        if not self._email.delivers:
            return CallSummaryOutcome.EMAIL_NOT_CONFIGURED
        zone = await self._zone(run.organization_id)
        if not await self._store.claim_call_summary_email(run_id, self._clock.now()):
            return CallSummaryOutcome.ALREADY_SENT
        # Counted after the claim, so a duplicate completion uses none of it.
        if not await self._within_daily_limit(run.organization_id):
            return CallSummaryOutcome.DAILY_LIMIT_REACHED

        messages = [
            self._message(recipient, run, summary, zone)
            for recipient in setting.recipients
        ]
        delivered = await self._send_all(messages)
        if delivered < len(messages):
            logger.warning(
                "Call summary for run {} reached {} of {} recipients",
                run_id,
                delivered,
                len(messages),
            )
        return CallSummaryOutcome.SENT if delivered else CallSummaryOutcome.FAILED

    async def _within_daily_limit(self, organization_id: int | None) -> bool:
        if organization_id is None:
            return True
        day = self._clock.now().astimezone(UTC).date().isoformat()
        try:
            async with asyncio.timeout(self._limiter_timeout):
                allowed = await self._limiter.allow(
                    f"call-summary:{organization_id}:{day}",
                    limit=self._daily_limit,
                    window=timedelta(days=1),
                )
        except TimeoutError:
            # Fail open, like the limiter itself does on a Redis error.
            logger.warning("Call summary daily limit unavailable; sending anyway")
            return True
        if not allowed:
            logger.warning(
                "Call summary daily limit of {} reached for organization {}",
                self._daily_limit,
                organization_id,
            )
        return allowed

    async def _send_all(self, messages: Sequence[EmailMessage]) -> int:
        """Send concurrently; the number delivered before the timeout.

        Every send is stopped before this returns or raises, so a cancelled
        job (ARQ timeout, worker shutdown) leaves no email going out behind it.
        """
        tasks = [asyncio.create_task(self._deliver(m)) for m in messages]
        try:
            _, pending = await asyncio.wait(tasks, timeout=self._send_timeout)
            if pending:
                logger.warning(
                    "Call summary sends still running after {}s were stopped",
                    self._send_timeout,
                )
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        delivered = 0
        for task in tasks:
            if task.cancelled():
                continue
            if (error := task.exception()) is not None:
                # One broken send must not lose the others' results.
                logger.error(
                    "Call summary send failed unexpectedly: {}", type(error).__name__
                )
            elif task.result():
                delivered += 1
        return delivered

    async def _deliver(self, message: EmailMessage) -> bool:
        attempt = 1
        while True:
            try:
                await self._email.send(message)
                return True
            except EmailDeliveryError as exc:
                logger.warning("Call summary email attempt {} failed: {}", attempt, exc)
                if attempt > self._retries_for(exc.failure):
                    return False
                await self._sleep(self._retry_delays[attempt - 1])
                attempt += 1

    def _retries_for(self, failure: EmailFailure) -> int:
        match failure:
            case EmailFailure.TRANSIENT:
                return len(self._retry_delays)
            case EmailFailure.PROVIDER_ERROR:
                return min(1, len(self._retry_delays))
            case EmailFailure.FINAL:
                return 0
            case _:
                assert_never(failure)

    async def _zone(self, organization_id: int | None) -> tzinfo | None:
        """The organization's timezone, or None when it set no usable one."""
        if organization_id is None:
            return None
        name = await self._timezone_of(organization_id)
        if not name:
            return None
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning("Unknown organization timezone; using UTC")
            return None

    def _message(
        self,
        recipient: str,
        run: CallSummaryRun,
        summary: CallSummary,
        zone: tzinfo | None,
    ) -> EmailMessage:
        started_at = run.started_at or self._clock.now()
        message = call_summary_message(
            to=recipient,
            agent_name=run.workflow_name,
            call_time=started_at.astimezone(zone or UTC).strftime(_TIME_FORMAT),
            caller_name=summary.caller_name,
            callback_number=summary.callback_number,
            reason=summary.reason,
            booking_lines=[booking_line(c, zone) for c in summary.booking_changes],
            run_url=f"{self._app_url}/workflow/{run.workflow_id}/run/{run.run_id}",
        )
        # Hashed: the address would make the key long and put it in headers.
        digest = hashlib.sha256(recipient.casefold().encode()).hexdigest()[:16]
        return replace(message, idempotency_key=f"call-summary-{run.run_id}-{digest}")


_OLD_BOOKING_KEPT = (
    ". The old booking could not be removed: delete it from the calendar."
)


@dataclass(frozen=True, slots=True)
class _Wording:
    label: str
    # The word before the appointment time.
    preposition: str
    # Anything staff must do about it.
    todo: str = ""


def _wording(action: BookingAction) -> _Wording:
    match action:
        case BookingAction.BOOKED:
            return _Wording("Booked", "for")
        case BookingAction.CANCELLED:
            return _Wording("Cancelled the appointment", "for")
        case BookingAction.MOVED:
            return _Wording("Moved the appointment", "to")
        case BookingAction.MOVED_OLD_KEPT:
            return _Wording("Moved the appointment", "to", _OLD_BOOKING_KEPT)
        case _:
            assert_never(action)


def booking_line(change: BookingChange, zone: tzinfo | None) -> str:
    """One line per booking change, e.g. "Booked for Tue 14 Oct 2026, 10:00
    IST (Mary, 0871234567)".

    Without an organization timezone the appointment keeps the calendar's own
    offset, which is the business's local time.
    """
    wording = _wording(change.action)
    when = ""
    if change.starts_at is not None:
        # astimezone(None) would mean the server's zone, not "keep it".
        starts_at = change.starts_at.astimezone(zone) if zone else change.starts_at
        when = f" {wording.preposition} {starts_at.strftime(_TIME_FORMAT)}"
    who = ", ".join(v for v in (change.caller_name, change.caller_phone) if v)
    return f"{wording.label}{when}{f' ({who})' if who else ''}{wording.todo}"
