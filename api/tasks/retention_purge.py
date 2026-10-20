"""Daily cron that enforces the data-retention periods the privacy policy promises."""

from api.services.retention import purge_expired_data


async def purge_expired_data_daily(_ctx) -> None:
    """Delete call content, visitor data and webhook payloads past retention.

    The purge is idempotent and marks what it has done, so an interrupted or
    timed-out pass simply continues the next day.
    """
    await purge_expired_data()
