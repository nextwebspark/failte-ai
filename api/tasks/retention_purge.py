"""Daily cron that enforces the data-retention periods the privacy policy promises."""

from loguru import logger

from api import constants
from api.services.retention import purge_expired_data


async def purge_expired_data_daily(_ctx) -> None:
    """Delete call content, visitor data and webhook payloads past retention.

    The purge is idempotent and marks what it has done, so an interrupted or
    timed-out pass simply continues the next day. ``RETENTION_PURGE_ENABLED``
    and ``RETENTION_PURGE_DRY_RUN`` gate the rollout.
    """
    if not constants.RETENTION_PURGE_ENABLED:
        logger.info("Retention purge is disabled (RETENTION_PURGE_ENABLED=false)")
        return
    await purge_expired_data(dry_run=constants.RETENTION_PURGE_DRY_RUN)
