"""Loading a run's call summary inputs and claiming its email, against the DB."""

import uuid
from datetime import UTC, datetime

from api.db.call_summary_client import WORKFLOW_RUN_CALL_SUMMARY_EMAILED_KEY
from api.db.models import OrganizationModel, UserModel, WorkflowRunModel
from api.db.retention_client import WORKFLOW_RUN_EXTRA_KEPT_KEYS

SETTING = {"call_summary_email": {"enabled": True, "recipients": ["o@bloom.ie"]}}
EVENT = {"type": "rtf-bot-text", "payload": {"text": "Hi"}}


async def _run(db_session, async_session):
    organization = OrganizationModel(provider_id=f"summary-{uuid.uuid4().hex}")
    async_session.add(organization)
    await async_session.flush()
    user = UserModel(
        provider_id=f"summary-{uuid.uuid4().hex}",
        selected_organization_id=organization.id,
    )
    async_session.add(user)
    await async_session.flush()
    workflow = await db_session.create_workflow(
        "Reception",
        {},
        user.id,
        organization.id,
        workflow_configurations=SETTING,
    )
    return await db_session.create_workflow_run(
        name="summary-run",
        workflow_id=workflow.id,
        mode="twilio",
        user_id=user.id,
        organization_id=organization.id,
        gathered_context={"extracted_variables": {"callback_number": "087"}},
        logs={"realtime_feedback_events": [EVENT, "not an event"]},
        definition_id=workflow.released_definition_id,
    )


async def test_loads_the_run_with_its_pinned_configuration(db_session, async_session):
    run = await _run(db_session, async_session)

    loaded = await db_session.get_call_summary_run(run.id)

    assert loaded is not None
    assert loaded.workflow_name == "Reception"
    assert loaded.mode == "twilio"
    assert loaded.workflow_configurations == SETTING
    assert loaded.gathered_context["extracted_variables"] == {"callback_number": "087"}
    assert loaded.realtime_events == [EVENT]
    assert await db_session.get_call_summary_run(run.id + 10_000) is None


async def test_a_run_is_claimed_once(db_session, async_session):
    run = await _run(db_session, async_session)
    claimed_at = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)

    assert await db_session.claim_call_summary_email(run.id, claimed_at) is True
    assert await db_session.claim_call_summary_email(run.id, claimed_at) is False

    stored = await async_session.get(WorkflowRunModel, run.id)
    await async_session.refresh(stored)
    assert stored.extra[WORKFLOW_RUN_CALL_SUMMARY_EMAILED_KEY] == claimed_at.isoformat()
    # Other run flags survive the claim.
    assert stored.extra["use_draft"] is False
    assert (
        await db_session.claim_call_summary_email(run.id + 10_000, claimed_at) is False
    )


def test_the_marker_outlives_the_retention_purge():
    assert WORKFLOW_RUN_CALL_SUMMARY_EMAILED_KEY in WORKFLOW_RUN_EXTRA_KEPT_KEYS
