"""Reviews one finished call and stores the review on it.

Runs as an ARQ job after a call's completion processing (and from the
backfill script). It never raises: a failed review is logged and the call is
left without one ("Not reviewed yet" on Home), nothing else changes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from loguru import logger

from api.db import db_client
from api.db.retention_client import is_purged_run
from api.enums import (
    WORKFLOW_RUN_MODES_BY_CHANNEL,
    CallType,
    OrganizationConfigurationKey,
    WorkflowRunChannel,
    WorkflowRunMode,
)
from api.services.call_notifications.outcome import MissedReason, missed_reason
from api.services.call_review.categories import reason_set, template_for_workflow
from api.services.call_review.llm import ask_reviewer
from api.services.call_review.review import (
    CALL_REVIEW_KEY,
    ReviewParseError,
    has_caller_speech,
    parse_review,
    response_schema,
    silent_review,
    stored_review,
    system_prompt,
    transcript_lines,
    user_prompt,
)

_PHONE_MODES = frozenset(
    WORKFLOW_RUN_MODES_BY_CHANNEL[WorkflowRunChannel.TELEPHONY.value]
)
_BROWSER_CALL_MODES = frozenset(
    {WorkflowRunMode.WEBRTC.value, WorkflowRunMode.SMALLWEBRTC.value}
)


class ReviewOutcome(StrEnum):
    REVIEWED = "reviewed"
    SILENT = "silent"
    ALREADY_REVIEWED = "already_reviewed"
    NOT_FOUND = "not_found"
    # Browser tests, text chats and outbound calls aren't reviewed.
    NOT_A_PHONE_CALL = "not_a_phone_call"
    NOT_FINISHED = "not_finished"
    NEVER_CONNECTED = "never_connected"
    CONTENT_DELETED = "content_deleted"
    NO_TRANSCRIPT = "no_transcript"
    FAILED = "failed"


async def review_call(workflow_run_id: int, *, redo: bool = False) -> ReviewOutcome:
    """Review a finished inbound phone call, once. ``redo`` reviews a call
    again even if it has a review (the backfill's ``--redo``)."""
    try:
        return await _review_call(workflow_run_id, redo=redo)
    except Exception as exc:  # noqa: BLE001 - a review must never affect the call
        logger.warning(
            f"Call review failed for run {workflow_run_id}: {type(exc).__name__}: {exc}"
        )
        return ReviewOutcome.FAILED


async def _review_call(workflow_run_id: int, *, redo: bool) -> ReviewOutcome:
    run, organization_id = await db_client.get_workflow_run_with_context(
        workflow_run_id
    )
    if run is None or organization_id is None or run.workflow is None:
        return ReviewOutcome.NOT_FOUND
    if run.call_type != CallType.INBOUND.value or (
        run.mode not in _PHONE_MODES
        # A demo workspace's browser test calls are reviewed like phone
        # calls, so a call made during a demo gets its summary too.
        and not (
            run.mode in _BROWSER_CALL_MODES
            and await db_client.get_configuration(
                organization_id, OrganizationConfigurationKey.DEMO_ACCOUNT.value
            )
            is not None
        )
    ):
        return ReviewOutcome.NOT_A_PHONE_CALL
    if not run.is_completed:
        return ReviewOutcome.NOT_FINISHED
    if is_purged_run(run):
        return ReviewOutcome.CONTENT_DELETED
    if stored_review(run.annotations) is not None and not redo:
        return ReviewOutcome.ALREADY_REVIEWED

    gathered = run.gathered_context or {}
    if (
        missed_reason(gathered, run.logs, run.usage_info)
        == MissedReason.NEVER_CONNECTED
    ):
        return ReviewOutcome.NEVER_CONNECTED

    definition = run.definition.workflow_json if run.definition else None
    reasons = reason_set(
        template_for_workflow(
            definition or run.workflow.workflow_definition,
            run.workflow.template_context_variables,
        )
    )
    now = datetime.now(UTC)

    if not has_caller_speech(gathered):
        await _store(workflow_run_id, silent_review(reasons, now=now))
        return ReviewOutcome.SILENT

    lines = transcript_lines(run.logs)
    if not any(speaker == "Caller" for speaker, _ in lines):
        logger.info(f"Call review skipped for run {workflow_run_id}: no transcript")
        return ReviewOutcome.NO_TRANSCRIPT

    answer = await ask_reviewer(
        organization_id=organization_id,
        system=system_prompt(reasons),
        user=user_prompt(lines, gathered),
        schema=response_schema(reasons),
    )
    try:
        review = parse_review(answer.text, reasons, model=answer.model, now=now)
    except ReviewParseError as exc:
        logger.warning(
            f"Call review for run {workflow_run_id} unusable ({exc}); not stored"
        )
        return ReviewOutcome.FAILED
    await _store(workflow_run_id, review)
    logger.info(
        f"Reviewed run {workflow_run_id} with {answer.model}: "
        f"{answer.prompt_tokens} prompt + {answer.output_tokens} output tokens"
    )
    return ReviewOutcome.REVIEWED


async def _store(workflow_run_id: int, review: dict) -> None:
    await db_client.update_workflow_run(
        workflow_run_id, annotations={CALL_REVIEW_KEY: review}
    )
