"""ARQ job: the short review written after each finished call."""

from loguru import logger
from pipecat.utils.run_context import set_current_run_id

from api.services.call_review.service import review_call


async def review_finished_call(_ctx, workflow_run_id: int) -> str:
    """Review one finished call (see ``api.services.call_review``). Never
    raises: a failed review leaves the call without one."""
    set_current_run_id(str(workflow_run_id))
    outcome = await review_call(workflow_run_id)
    logger.info(f"Call review for run {workflow_run_id}: {outcome}")
    return outcome.value


async def enqueue_call_review(workflow_run_id: int) -> None:
    """Queue the review; one job per call, however often this is asked."""
    from api.tasks.arq import enqueue_job
    from api.tasks.function_names import FunctionNames

    try:
        await enqueue_job(
            FunctionNames.REVIEW_FINISHED_CALL,
            workflow_run_id,
            _job_id=f"call-review-{workflow_run_id}",
        )
    except Exception as exc:  # noqa: BLE001 - never affects the call
        logger.warning(
            f"Could not queue the call review for run {workflow_run_id}: "
            f"{type(exc).__name__}"
        )
