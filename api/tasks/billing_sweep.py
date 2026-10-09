"""Safety net that charges completed calls the completion job failed to bill."""

from datetime import UTC, datetime, timedelta

from loguru import logger

from api.constants import BILLING_PROVIDER
from api.db import db_client
from api.enums import WorkflowRunMode
from api.services.workflow_run_billing import report_workflow_run_platform_usage

# Leave the completion job time to charge first.
SWEEP_GRACE = timedelta(minutes=10)
# How far back to look; older misses need a manual adjustment.
SWEEP_LOOKBACK = timedelta(days=7)


async def sweep_uncharged_workflow_runs(_ctx) -> None:
    """Charge completed calls that have talk time but no usage ledger entry.

    A transient failure in the completion job (DB blip, lock timeout) is
    logged and dropped there; this picks those runs up. Charging is
    idempotent per run, so overlapping with a late completion job is safe.
    """
    if BILLING_PROVIDER != "stripe":
        return

    now = datetime.now(UTC)
    run_ids = await db_client.list_uncharged_workflow_run_ids(
        completed_before=now - SWEEP_GRACE,
        created_after=now - SWEEP_LOOKBACK,
        text_chat_mode=WorkflowRunMode.TEXTCHAT.value,
    )
    charged = 0
    for run_id in run_ids:
        try:
            workflow_run = await db_client.get_workflow_run_by_id(run_id)
            if workflow_run is None:
                continue
            await report_workflow_run_platform_usage(workflow_run)
            charged += 1
        except Exception:
            logger.error(
                "Billing sweep could not charge workflow run {}", run_id, exc_info=True
            )
    if run_ids:
        logger.warning(
            "Billing sweep charged {} of {} uncharged workflow run(s)",
            charged,
            len(run_ids),
        )
