"""Real PostgreSQL coverage for the agent list's run activity query."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from api.db import db_client
from api.db.models import (
    EmbedTokenModel,
    OrganizationModel,
    TelephonyConfigurationModel,
    TelephonyPhoneNumberModel,
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

        def run(hours_ago: float, **fields) -> WorkflowRunModel:
            return WorkflowRunModel(
                name="run",
                workflow_id=busy.id,
                mode=fields.pop("mode", "webrtc"),
                created_at=NOW - timedelta(hours=hours_ago),
                **fields,
            )

        session.add_all(
            [
                # today, and a call still connected
                run(0.1, state="running", usage_info={"call_duration_seconds": 90.4}),
                # still inside today's rolling 24 hours
                run(
                    23,
                    state="completed",
                    is_completed=True,
                    usage_info={"call_duration_seconds": 30},
                ),
                # yesterday: its call time isn't today's
                run(25, usage_info={"call_duration_seconds": 600}),
                # oldest day in the window; left "running" by a crash, so not live
                run(24 * 6 + 1, state="running"),
                # outside the window, still counted in the total
                run(24 * 9),
                # clock skew: a run "from the future" counts as today. A text
                # chat is never a live call, and its open time isn't talk time.
                run(
                    -2,
                    mode="textchat",
                    state="running",
                    usage_info={"call_duration_seconds": 500},
                ),
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
    assert activity[busy.id].talk_seconds_24h == 120
    assert activity[busy.id].live_calls == 1

    assert activity[quiet.id].total_runs == 0
    assert activity[quiet.id].last_run_at is None
    assert activity[quiet.id].daily_runs == [0] * 7
    assert activity[quiet.id].talk_seconds_24h == 0
    assert activity[quiet.id].live_calls == 0


async def test_run_activity_with_no_ids_skips_the_database():
    assert await db_client.get_workflow_run_activity([]) == {}


async def test_workflow_ids_with_draft_returns_only_drafted_workflows(workflows):
    busy, quiet = workflows

    assert await db_client.get_workflow_ids_with_draft([busy.id, quiet.id]) == {
        quiet.id
    }
    assert await db_client.get_workflow_ids_with_draft([]) == set()


async def test_workflow_channels_reports_phone_numbers_and_widgets(workflows, sessions):
    busy, quiet = workflows
    async with sessions() as session:
        config = TelephonyConfigurationModel(
            organization_id=busy.organization_id, name="twilio", provider="twilio"
        )
        # Deactivated: its numbers no longer route calls.
        parked = TelephonyConfigurationModel(
            organization_id=busy.organization_id,
            name="parked",
            provider="twilio",
            inactive=True,
        )
        session.add_all([config, parked])
        await session.flush()

        def number(address: str, workflow_id: int, active: bool = True, cfg=config):
            return TelephonyPhoneNumberModel(
                organization_id=busy.organization_id,
                telephony_configuration_id=cfg.id,
                address=address,
                address_normalized=address,
                address_type="pstn",
                inbound_workflow_id=workflow_id,
                is_active=active,
            )

        def widget(workflow_id: int, **fields):
            return EmbedTokenModel(
                token=uuid.uuid4().hex,
                workflow_id=workflow_id,
                organization_id=busy.organization_id,
                created_by=busy.user_id,
                **fields,
            )

        session.add_all(
            [
                number("+35310000001", busy.id),
                number("+35310000002", busy.id),
                number("+35310000003", quiet.id, active=False),
                number("+35310000004", quiet.id, cfg=parked),
                widget(busy.id),
                widget(quiet.id, is_active=False),
                widget(quiet.id, expires_at=NOW - timedelta(days=1)),
                widget(quiet.id, usage_limit=5, usage_count=5),
            ]
        )
        await session.commit()

    try:
        channels = await db_client.get_workflow_channels(
            [busy.id, quiet.id], organization_id=busy.organization_id, now=NOW
        )
        assert channels == {busy.id: {"phone", "web"}, quiet.id: set()}
        assert (
            await db_client.get_workflow_channels(
                [], organization_id=busy.organization_id
            )
            == {}
        )
    finally:
        async with sessions() as session:
            await session.execute(
                delete(EmbedTokenModel).where(
                    EmbedTokenModel.workflow_id.in_([busy.id, quiet.id])
                )
            )
            await session.execute(
                delete(TelephonyConfigurationModel).where(
                    TelephonyConfigurationModel.id.in_([config.id, parked.id])
                )
            )
            await session.commit()
