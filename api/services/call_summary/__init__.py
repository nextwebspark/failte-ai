from api.constants import UI_APP_URL
from api.db import db_client
from api.services.call_summary.notifier import CallSummaryNotifier, CallSummaryOutcome
from api.services.email import get_email_sender
from api.services.organization_preferences import get_organization_preferences
from api.utils.clock import SystemClock


async def _organization_timezone(organization_id: int) -> str | None:
    return (await get_organization_preferences(organization_id)).timezone


def get_call_summary_notifier() -> CallSummaryNotifier:
    """The notifier wired to the real DB, mailer and organization settings."""
    return CallSummaryNotifier(
        store=db_client,
        email_sender=get_email_sender(),
        clock=SystemClock(),
        timezone_of=_organization_timezone,
        app_url=UI_APP_URL,
    )


__all__ = ["CallSummaryNotifier", "CallSummaryOutcome", "get_call_summary_notifier"]
