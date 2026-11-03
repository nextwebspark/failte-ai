"""Email the business what a finished call left for it.

Runs as the last step of the completion job. Sending is at most once per run:
the run is claimed before the first email goes out, so a re-run job (worker
restart, duplicate completion) never repeats it, and a crash between the claim
and the send loses that summary rather than duplicating it.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, tzinfo
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger

from api.db.call_summary_client import CallSummaryRun
from api.enums import WORKFLOW_RUN_MODES_BY_CHANNEL, WorkflowRunChannel
from api.schemas.call_summary_email import (
    CallSummaryEmailConfiguration,
    resolve_call_summary_email,
)
from api.services.call_summary.ports import CallSummaryStore, TimezoneLookup
from api.services.call_summary.summary import (
    BookingAction,
    BookingChange,
    CallSummary,
    extract_call_summary,
)
from api.services.email.base import EmailDeliveryError, EmailMessage, EmailSender
from api.services.email.templates import call_summary_message
from api.utils.clock import Clock

_PHONE_MODES = frozenset(
    WORKFLOW_RUN_MODES_BY_CHANNEL[WorkflowRunChannel.TELEPHONY.value]
)
# Waits before the second and third attempt at one recipient. Short: the job
# holds a worker slot, and most failures (a rejected domain or key) persist.
DEFAULT_RETRY_DELAYS_SECONDS = (2.0, 8.0)
_TIME_FORMAT = "%a %d %b %Y, %H:%M %Z"


class CallSummaryOutcome(StrEnum):
    SENT = "sent"
    # Claimed, but no recipient could be reached.
    FAILED = "failed"
    ALREADY_SENT = "already_sent"
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
    if not setting.enabled or not setting.recipients:
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
        app_url: str,
        retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._store = store
        self._email = email_sender
        self._clock = clock
        self._timezone_of = timezone_of
        self._app_url = app_url.rstrip("/")
        self._retry_delays = tuple(retry_delays)
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
        summary = extract_call_summary(run.gathered_context, run.realtime_events)
        if summary is None:
            return CallSummaryOutcome.NOTHING_TO_REPORT
        # The logging fallback would write the caller's details to the log.
        if not self._email.delivers:
            return CallSummaryOutcome.EMAIL_NOT_CONFIGURED
        zone = await self._zone(run.organization_id)
        if not await self._store.claim_call_summary_email(run_id, self._clock.now()):
            return CallSummaryOutcome.ALREADY_SENT

        delivered = 0
        for recipient in setting.recipients:
            if await self._deliver(self._message(recipient, run, summary, zone)):
                delivered += 1
        if delivered < len(setting.recipients):
            logger.warning(
                "Call summary for run {} reached {} of {} recipients",
                run_id,
                delivered,
                len(setting.recipients),
            )
        return CallSummaryOutcome.SENT if delivered else CallSummaryOutcome.FAILED

    async def _deliver(self, message: EmailMessage) -> bool:
        for attempt, delay in enumerate((0.0, *self._retry_delays), start=1):
            if delay:
                await self._sleep(delay)
            try:
                await self._email.send(message)
                return True
            except EmailDeliveryError as exc:
                logger.warning("Call summary email attempt {} failed: {}", attempt, exc)
        return False

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
        return call_summary_message(
            to=recipient,
            agent_name=run.workflow_name,
            call_time=started_at.astimezone(zone or UTC).strftime(_TIME_FORMAT),
            caller_name=summary.caller_name,
            callback_number=summary.callback_number,
            reason=summary.reason,
            booking_lines=[booking_line(c, zone) for c in summary.booking_changes],
            run_url=f"{self._app_url}/workflow/{run.workflow_id}/run/{run.run_id}",
        )


def booking_line(change: BookingChange, zone: tzinfo | None) -> str:
    """One line per booking change, e.g. "Booked for Tue 14 Oct 2026, 10:00
    IST (Mary, 0871234567)".

    Without an organization timezone the appointment keeps the calendar's own
    offset, which is the business's local time.
    """
    who = ", ".join(v for v in (change.caller_name, change.caller_phone) if v)
    suffix = f" ({who})" if who else ""
    match change.action:
        case BookingAction.BOOKED:
            if change.starts_at is None:
                return f"Booked{suffix}"
            # astimezone(None) would mean the server's zone, not "keep it".
            starts_at = change.starts_at.astimezone(zone) if zone else change.starts_at
            return f"Booked for {starts_at.strftime(_TIME_FORMAT)}{suffix}"
        case BookingAction.CANCELLED:
            told = f': "{change.confirmation}"' if change.confirmation else ""
            return f"Cancelled an appointment{suffix}{told}"
