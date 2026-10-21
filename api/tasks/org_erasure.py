"""Daily cron that erases organisations whose deletion grace period has ended."""

from loguru import logger

from api import constants
from api.services.privacy.org_erasure import erase_deleted_organizations


async def erase_deleted_organizations_daily(_ctx) -> None:
    """Permanently erase organisations scheduled for deletion that are due.

    Resumable: each organisation's erasure commits phase by phase, so an
    interrupted or failed pass continues the next day. ``ORG_ERASURE_ENABLED``
    is the kill switch.
    """
    if not constants.ORG_ERASURE_ENABLED:
        logger.info("Organisation erasure is disabled (ORG_ERASURE_ENABLED=false)")
        return
    await erase_deleted_organizations()
