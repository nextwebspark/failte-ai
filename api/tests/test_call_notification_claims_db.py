"""The at-most-once claim against Postgres (runs where a test database is
available, e.g. CI)."""

import uuid

from sqlalchemy import select

from api.db.models import (
    CallNotificationModel,
    OrganizationModel,
    UserModel,
    WorkflowModel,
    WorkflowRunModel,
)


async def _run(session) -> WorkflowRunModel:
    org = OrganizationModel(provider_id=f"notify-{uuid.uuid4().hex}")
    session.add(org)
    await session.flush()
    user = UserModel(
        provider_id=f"notify-{uuid.uuid4().hex}", selected_organization_id=org.id
    )
    session.add(user)
    await session.flush()
    workflow = WorkflowModel(name="Reception", user_id=user.id, organization_id=org.id)
    session.add(workflow)
    await session.flush()
    run = WorkflowRunModel(
        name="WR-TEL-IN-1",
        workflow_id=workflow.id,
        mode="twilio",
        call_type="inbound",
        storage_backend="minio",
        initial_context={},
        gathered_context={},
    )
    session.add(run)
    await session.flush()
    return run


async def test_each_channel_is_claimed_once(db_session, async_session):
    run = await _run(async_session)

    assert await db_session.claim_call_notification(run.id, "email", "booking_made")
    assert not await db_session.claim_call_notification(run.id, "email", "booking_made")
    # The other channel is separate.
    assert await db_session.claim_call_notification(run.id, "sms", "booking_made")

    await db_session.finish_call_notification(
        run.id, "email", status="partial", recipient_count=2, error="x" * 900
    )
    rows = (
        await async_session.execute(
            select(CallNotificationModel).where(
                CallNotificationModel.workflow_run_id == run.id
            )
        )
    ).scalars()
    by_channel = {row.channel: row for row in rows}
    assert by_channel["email"].status == "partial"
    assert by_channel["email"].recipient_count == 2
    assert len(by_channel["email"].error) == 500
    assert by_channel["sms"].status == "sending"
