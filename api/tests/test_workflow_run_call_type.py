"""update_workflow_run can correct a run's call_type (Cloudonix agent stream)."""

from __future__ import annotations

import uuid

import pytest

from api.db.models import OrganizationModel, UserModel, WorkflowModel, WorkflowRunModel
from api.enums import CallType


@pytest.mark.asyncio
async def test_update_workflow_run_sets_the_call_type(db_session, async_session):
    org = OrganizationModel(provider_id=f"calltype-{uuid.uuid4().hex}")
    async_session.add(org)
    await async_session.flush()
    user = UserModel(
        provider_id=f"calltype-{uuid.uuid4().hex}", selected_organization_id=org.id
    )
    async_session.add(user)
    await async_session.flush()
    workflow = WorkflowModel(name="Calls", user_id=user.id, organization_id=org.id)
    async_session.add(workflow)
    await async_session.flush()
    run = WorkflowRunModel(
        name="WR-AGS-1",
        workflow_id=workflow.id,
        mode="cloudonix",
        call_type=CallType.INBOUND.value,
        initial_context={"direction": "inbound"},
    )
    async_session.add(run)
    await async_session.flush()

    untouched = await db_session.update_workflow_run(run.id, state="running")
    assert untouched.call_type == CallType.INBOUND.value

    updated = await db_session.update_workflow_run(
        run.id, call_type=CallType.OUTBOUND, initial_context={"direction": "outbound"}
    )
    assert updated.call_type == CallType.OUTBOUND.value
    stored = await db_session.get_workflow_run(run.id, organization_id=org.id)
    assert stored.call_type == CallType.OUTBOUND.value
