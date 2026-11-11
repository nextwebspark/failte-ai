"""ARQ cron: send the emailed call reports that are due."""

from loguru import logger

from api.services.email_reports.service import send_due_reports


async def send_due_email_reports(_ctx) -> None:
    """Every 15 minutes. Each workspace's report is claimed before it is
    sent (see ``api.services.email_reports.service``), so overlapping runs,
    retries or two workers never send the same report twice."""
    totals = await send_due_reports()
    if totals["reports"]:
        logger.info(f"[email-reports] cron pass: {totals}")
