"""Composition root: the notifier wired to the real DB, mailer and Redis."""

from api.constants import CALL_SUMMARY_DAILY_LIMIT, UI_APP_URL
from api.db import db_client
from api.services.call_summary.notifier import CallSummaryNotifier
from api.services.email import get_email_sender
from api.services.organization_preferences import get_organization_preferences
from api.services.rate_limit import get_rate_limiter
from api.utils.clock import SystemClock


async def _organization_timezone(organization_id: int) -> str | None:
    return (await get_organization_preferences(organization_id)).timezone


def get_call_summary_notifier() -> CallSummaryNotifier:
    return CallSummaryNotifier(
        store=db_client,
        email_sender=get_email_sender(),
        clock=SystemClock(),
        timezone_of=_organization_timezone,
        rate_limiter=get_rate_limiter(),
        daily_limit=CALL_SUMMARY_DAILY_LIMIT,
        app_url=UI_APP_URL,
    )
