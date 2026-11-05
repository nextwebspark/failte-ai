"""Usage history names the other party of each call as phone_number."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from api.db.models import OrganizationModel, UserModel, WorkflowModel, WorkflowRunModel
from api.enums import CallType


@pytest.mark.asyncio
async def test_phone_number_is_the_other_party(db_session, async_session):
    org = OrganizationModel(provider_id=f"usage-{uuid.uuid4().hex}")
    async_session.add(org)
    await async_session.flush()
    user = UserModel(
        provider_id=f"usage-{uuid.uuid4().hex}", selected_organization_id=org.id
    )
    async_session.add(user)
    await async_session.flush()
    workflow = WorkflowModel(name="Calls", user_id=user.id, organization_id=org.id)
    async_session.add(workflow)
    await async_session.flush()

    def run(name: str, call_type: CallType, context: dict[str, Any]) -> None:
        async_session.add(
            WorkflowRunModel(
                name=name,
                workflow_id=workflow.id,
                mode="cloudonix",
                call_type=call_type.value,
                initial_context=context,
                usage_info={"call_duration_seconds": 10},
            )
        )

    business, customer = "+15551230001", "+15559870002"
    run(
        "inbound",
        CallType.INBOUND,
        {"caller_number": customer, "called_number": business},
    )
    # Dispatchers write phone_number; a Cloudonix agent-stream outbound run
    # has only called_number.
    run(
        "dispatched",
        CallType.OUTBOUND,
        {"phone_number": customer, "caller_number": business},
    )
    run(
        "agent-stream",
        CallType.OUTBOUND,
        {"caller_number": business, "called_number": customer},
    )
    await async_session.flush()

    runs, total, _, _ = await db_session.get_usage_history(org.id)

    assert total == 3
    assert {r["name"]: r["phone_number"] for r in runs} == {
        "inbound": customer,
        "dispatched": customer,
        "agent-stream": customer,
    }
