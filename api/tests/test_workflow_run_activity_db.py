"""Real PostgreSQL coverage for the agent list's run activity query."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from api.db import db_client
from api.db.models import (
    OrganizationModel,
    UserModel,
    WorkflowDefinitionModel,
    WorkflowModel,
    WorkflowRunModel,
)
from api.tests import test_campaign_call_dispatcher as fixtures
from api.tests.conftest import DEFAULT_WORKFLOW_DEFINITION

sessions = fixtures.sessions

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
async def workflows(sessions):
    async with sessions() as session:
        org = OrganizationModel(provider_id=f"activity-{uuid.uuid4().hex}")
        session.add(org)
        await session.flush()
        user = UserModel(
            provider_id=f"activity-{uuid.uuid4().hex}", selected_organization_id=org.id
        )
        session.add(user)
        await session.flush()
        busy, quiet = (
            WorkflowModel(name=name, user_id=user.id, organization_id=org.id)
            for name in ("busy", "quiet")
        )
        session.add_all([busy, quiet])
        await session.flush()

        def run(hours_ago: float) -> WorkflowRunModel:
            return WorkflowRunModel(
                name="run",
                workflow_id=busy.id,
                mode="webrtc",
                created_at=NOW - timedelta(hours=hours_ago),
            )

        session.add_all(
            [
                run(1),  # today
                run(23),  # still inside today's rolling 24 hours
                run(25),  # yesterday
                run(24 * 6 + 1),  # oldest day in the window
                run(24 * 9),  # outside the window, still counted in the total
                run(-2),  # clock skew: a run "from the future" counts as today
            ]
        )
        session.add(
            WorkflowDefinitionModel(
                workflow_id=quiet.id,
                workflow_json=DEFAULT_WORKFLOW_DEFINITION,
                status="draft",
                version_number=2,
                workflow_configurations={},
            )
        )
        await session.commit()

    yield busy, quiet

    async with sessions() as session:
        ids = [busy.id, quiet.id]
        await session.execute(
            delete(WorkflowRunModel).where(WorkflowRunModel.workflow_id.in_(ids))
        )
        await session.execute(
            delete(WorkflowDefinitionModel).where(
                WorkflowDefinitionModel.workflow_id.in_(ids)
            )
        )
        await session.execute(delete(WorkflowModel).where(WorkflowModel.id.in_(ids)))
        await session.execute(delete(UserModel).where(UserModel.id == user.id))
        await session.execute(
            delete(OrganizationModel).where(OrganizationModel.id == org.id)
        )
        await session.commit()


async def test_run_activity_buckets_runs_into_rolling_days(workflows):
    busy, quiet = workflows

    activity = await db_client.get_workflow_run_activity([busy.id, quiet.id], now=NOW)

    assert activity[busy.id].total_runs == 6
    assert activity[busy.id].last_run_at == NOW + timedelta(hours=2)
    # Oldest first: six days ago ... today.
    assert activity[busy.id].daily_runs == [1, 0, 0, 0, 0, 1, 3]

    assert activity[quiet.id].total_runs == 0
    assert activity[quiet.id].last_run_at is None
    assert activity[quiet.id].daily_runs == [0] * 7


async def test_run_activity_with_no_ids_skips_the_database():
    assert await db_client.get_workflow_run_activity([]) == {}


async def test_workflow_ids_with_draft_returns_only_drafted_workflows(workflows):
    busy, quiet = workflows

    assert await db_client.get_workflow_ids_with_draft([busy.id, quiet.id]) == {
        quiet.id
    }
    assert await db_client.get_workflow_ids_with_draft([]) == set()
