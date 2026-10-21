"""Data-retention purge: the retention setting and what a pass deletes and keeps."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from loguru import logger
from pydantic import ValidationError
from sqlalchemy import select

from api.db import db_client
from api.db.models import (
    CampaignModel,
    EmbedSessionModel,
    EmbedTokenModel,
    OrganizationModel,
    QueuedRunModel,
    UserModel,
    WebhookDeliveryModel,
    WorkflowModel,
    WorkflowRunModel,
    WorkflowRunTextSessionModel,
)
from api.db.retention_client import ExpiredCampaign
from api.enums import OrganizationConfigurationKey
from api.routes import organization as routes
from api.schemas.organization_preferences import (
    DEFAULT_CALL_DATA_RETENTION_DAYS,
    OrganizationPreferences,
)
from api.services.observability.call_events import configuration
from api.services.organization_preferences import get_call_data_retention_days
from api.services.retention import purge_expired_data
from api.services.retention.purge import _is_run_artifact_key
from api.tasks import retention_purge

NOW = datetime(2026, 10, 20, 3, 17, tzinfo=UTC)


# --- retention setting ------------------------------------------------------


def test_retention_defaults_to_90_days():
    assert DEFAULT_CALL_DATA_RETENTION_DAYS == 90
    assert OrganizationPreferences().call_data_retention_days == 90


@pytest.mark.parametrize("days", [1, 30, 365])
def test_retention_accepts_1_to_365_days(days):
    assert (
        OrganizationPreferences(call_data_retention_days=days).call_data_retention_days
        == days
    )


@pytest.mark.parametrize("days", [0, -5, 366, 1000])
def test_retention_rejects_out_of_range_days(days):
    with pytest.raises(ValidationError):
        OrganizationPreferences(call_data_retention_days=days)


@pytest.fixture
async def preferences_client(monkeypatch):
    rows = {}
    user = SimpleNamespace(selected_organization_id=7)

    async def get(org_id, key):
        value = rows.get((org_id, key))
        return SimpleNamespace(value=value) if value is not None else None

    async def put(org_id, key, value):
        rows[(org_id, key)] = value

    async def delete(org_id, key):
        rows.pop((org_id, key), None)

    monkeypatch.setattr(configuration.db_client, "get_configuration", get)
    monkeypatch.setattr(configuration.db_client, "upsert_configuration", put)
    monkeypatch.setattr(configuration.db_client, "delete_configuration", delete)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_user] = lambda: user
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, rows


async def test_retention_round_trips_through_preferences_api(preferences_client):
    client, rows = preferences_client
    url = "/organizations/preferences"
    prefs_key = OrganizationConfigurationKey.ORGANIZATION_PREFERENCES.value

    assert (await client.get(url)).json()["call_data_retention_days"] == 90

    response = await client.put(url, json={"call_data_retention_days": 30})
    assert response.status_code == 200
    assert response.json()["call_data_retention_days"] == 30
    assert rows[(7, prefs_key)]["call_data_retention_days"] == 30

    # Saving another preference leaves the period alone.
    await client.put(url, json={"timezone": "Europe/Dublin"})
    assert (await client.get(url)).json()["call_data_retention_days"] == 30

    for invalid in (0, 366):
        response = await client.put(url, json={"call_data_retention_days": invalid})
        assert response.status_code == 422
    assert rows[(7, prefs_key)]["call_data_retention_days"] == 30


class FakeConfigurationDB:
    def __init__(self, rows):
        self.rows = rows

    async def get_configuration(self, organization_id, key):
        value = self.rows.get(key)
        return SimpleNamespace(value=value) if value is not None else None


PREFS_KEY = OrganizationConfigurationKey.ORGANIZATION_PREFERENCES.value
LEGACY_PREFS_KEY = OrganizationConfigurationKey.MODEL_CONFIGURATION_PREFERENCES.value


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ({}, 90),
        ({PREFS_KEY: {}}, 90),
        ({PREFS_KEY: {"timezone": "UTC"}}, 90),
        ({PREFS_KEY: {"call_data_retention_days": 365}}, 365),
        ({LEGACY_PREFS_KEY: {"call_data_retention_days": 30}}, 30),
        # An unrelated invalid preference does not reset the period.
        (
            {
                PREFS_KEY: {
                    "call_data_retention_days": 365,
                    "disposition_mapping": "not a mapping",
                }
            },
            365,
        ),
        ({PREFS_KEY: {"call_data_retention_days": 0}}, None),
        ({PREFS_KEY: {"call_data_retention_days": 366}}, None),
        ({PREFS_KEY: {"call_data_retention_days": "forever"}}, None),
        ({PREFS_KEY: {"call_data_retention_days": True}}, None),
        ({PREFS_KEY: {"call_data_retention_days": None}}, None),
        ({PREFS_KEY: ["not", "an", "object"]}, None),
    ],
)
async def test_retention_days_are_read_strictly(rows, expected):
    days = await get_call_data_retention_days(7, db=FakeConfigurationDB(rows))
    assert days == expected


def test_only_a_runs_own_keys_count_as_its_artifacts():
    assert _is_run_artifact_key(12, "recordings/12.wav")
    assert _is_run_artifact_key(12, "recordings/12/user.wav")
    assert _is_run_artifact_key(12, "recordings/12/noveum/user/abc.wav")
    assert _is_run_artifact_key(12, "transcripts/12.txt")
    # Agent prompt audio of organization 12, and other runs' objects.
    assert not _is_run_artifact_key(12, "recordings/12/AbCd1234/greeting.wav")
    assert not _is_run_artifact_key(12, "recordings/123.wav")
    assert not _is_run_artifact_key(12, "transcripts/1.txt")
    assert not _is_run_artifact_key(12, "campaigns/12/list.csv")


# --- purge pass -------------------------------------------------------------


class FakeStorage:
    """In-memory object store recording what the purge deletes."""

    def __init__(self):
        self.objects: set[str] = set()
        self.failing: set[str] = set()

    def add(self, *keys: str) -> None:
        self.objects.update(keys)

    async def adelete_file(self, file_path: str) -> bool:
        if file_path in self.failing:
            return False
        self.objects.discard(file_path)
        return True

    async def adelete_prefix(self, prefix: str) -> int:
        keys = [key for key in self.objects if key.startswith(prefix)]
        self.objects.difference_update(keys)
        return len(keys)


@pytest.fixture
def storage():
    return FakeStorage()


async def purge(storage):
    return await purge_expired_data(now=NOW, resolve_storage=lambda _backend: storage)


async def make_org(session, retention_days=None):
    org = OrganizationModel(provider_id=f"retention-{uuid.uuid4().hex}")
    session.add(org)
    await session.flush()
    user = UserModel(
        provider_id=f"retention-{uuid.uuid4().hex}", selected_organization_id=org.id
    )
    session.add(user)
    await session.flush()
    workflow = WorkflowModel(name="Agent", user_id=user.id, organization_id=org.id)
    session.add(workflow)
    await session.flush()
    return SimpleNamespace(org=org, user=user, workflow=workflow)


async def set_retention(db_session, org_id, days):
    await db_session.upsert_configuration(
        org_id,
        OrganizationConfigurationKey.ORGANIZATION_PREFERENCES.value,
        {"timezone": "UTC", "call_data_retention_days": days},
    )


async def make_run(
    session,
    storage,
    workflow,
    age_days,
    *,
    text_session=False,
    completed=True,
    chat_updated_days_ago=None,
):
    run = WorkflowRunModel(
        name="call",
        workflow_id=workflow.id,
        mode="twilio",
        storage_backend="minio",
        created_at=NOW - timedelta(days=age_days),
        initial_context={"caller_number": "+353870000001", "called_number": "+3531"},
        gathered_context={
            "call_id": "CA123",
            "call_disposition": "user_hangup",
            "mapped_call_disposition": "HUNGUP",
            "extracted_variables": {"name": "Aoife"},
        },
        logs={"realtime_feedback_events": [{"text": "Hello, my name is Aoife"}]},
        annotations={"note": "called back"},
        usage_info={"call_duration_seconds": 42},
        cost_info={"total": 0.12},
        public_access_token=str(uuid.uuid4()),
        state="completed" if completed else "running",
        is_completed=completed,
    )
    session.add(run)
    await session.flush()
    run.recording_url = f"recordings/{run.id}.wav"
    run.transcript_url = f"transcripts/{run.id}.txt"
    run.extra = {
        "use_draft": False,
        "caller_name": "Aoife",
        "recordings": {
            track: {
                "storage_key": key,
                "storage_backend": "minio",
                "format": "wav",
                "track": track,
            }
            for track, key in (
                ("mixed", f"recordings/{run.id}.wav"),
                ("user", f"recordings/{run.id}/user.wav"),
                ("bot", f"recordings/{run.id}/bot.wav"),
            )
        },
    }
    storage.add(
        f"recordings/{run.id}.wav",
        f"recordings/{run.id}/user.wav",
        f"recordings/{run.id}/bot.wav",
        f"recordings/{run.id}/noveum/user/seg-1.wav",
        f"transcripts/{run.id}.txt",
    )
    if text_session:
        chat_updated = NOW - timedelta(
            days=age_days if chat_updated_days_ago is None else chat_updated_days_ago
        )
        session.add(
            WorkflowRunTextSessionModel(
                workflow_run_id=run.id,
                session_data={"messages": [{"role": "user", "content": "hi"}]},
                checkpoint={"messages": ["hi"]},
                created_at=chat_updated,
                updated_at=chat_updated,
            )
        )
    await session.flush()
    return run


def run_keys(run_id):
    return {
        f"recordings/{run_id}.wav",
        f"recordings/{run_id}/user.wav",
        f"recordings/{run_id}/bot.wav",
        f"recordings/{run_id}/noveum/user/seg-1.wav",
        f"transcripts/{run_id}.txt",
    }


async def test_expired_run_objects_are_deleted_and_content_scrubbed(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    run = await make_run(async_session, storage, data.workflow, 91, text_session=True)
    # Prompt audio of an organization whose id matches the run id must survive.
    agent_audio = f"recordings/{run.id}/AbCd1234/greeting.wav"
    storage.add(agent_audio)
    await async_session.commit()

    result = await purge(storage)

    assert result.runs_purged >= 1
    assert storage.objects.isdisjoint(run_keys(run.id))
    assert agent_audio in storage.objects

    await async_session.refresh(run)
    assert run.recording_url is None
    assert run.transcript_url is None
    assert run.logs == {}
    assert run.initial_context == {}
    assert run.annotations == {}
    assert run.public_access_token is None
    assert run.gathered_context == {
        "call_disposition": "user_hangup",
        "mapped_call_disposition": "HUNGUP",
    }
    assert run.extra == {"use_draft": False, "purged_at": NOW.isoformat()}
    # Billing and usage metadata stays.
    assert run.usage_info == {"call_duration_seconds": 42}
    assert run.cost_info == {"total": 0.12}
    assert run.state == "completed"
    assert run.workflow_id == data.workflow.id

    text_session = (
        await async_session.execute(
            select(WorkflowRunTextSessionModel).where(
                WorkflowRunTextSessionModel.workflow_run_id == run.id
            )
        )
    ).scalar_one()
    await async_session.refresh(text_session)
    assert text_session.session_data == {}
    assert text_session.checkpoint == {}


async def test_runs_inside_retention_are_untouched(db_session, async_session, storage):
    data = await make_org(async_session)
    run = await make_run(async_session, storage, data.workflow, 89)
    await async_session.commit()

    await purge(storage)

    assert run_keys(run.id) <= storage.objects
    await async_session.refresh(run)
    assert run.recording_url == f"recordings/{run.id}.wav"
    assert run.initial_context["caller_number"] == "+353870000001"
    assert "purged_at" not in run.extra


async def test_per_organization_retention_period(db_session, async_session, storage):
    short = await make_org(async_session)
    long = await make_org(async_session)
    await async_session.commit()
    await set_retention(db_session, short.org.id, 30)
    await set_retention(db_session, long.org.id, 365)
    short_run = await make_run(async_session, storage, short.workflow, 31)
    long_run = await make_run(async_session, storage, long.workflow, 200)
    very_old_run = await make_run(async_session, storage, long.workflow, 366)
    await async_session.commit()

    await purge(storage)

    assert storage.objects.isdisjoint(run_keys(short_run.id))
    assert run_keys(long_run.id) <= storage.objects
    assert storage.objects.isdisjoint(run_keys(very_old_run.id))
    for run, purged in ((short_run, True), (long_run, False), (very_old_run, True)):
        await async_session.refresh(run)
        assert ("purged_at" in run.extra) is purged


async def test_purge_is_idempotent(db_session, async_session, storage):
    data = await make_org(async_session)
    run = await make_run(async_session, storage, data.workflow, 120)
    await async_session.commit()

    await purge(storage)
    await async_session.refresh(run)
    first_extra = dict(run.extra)

    # A second pass finds nothing left to do for this run.
    storage.add(f"recordings/{run.id}.wav")  # would be deleted if reprocessed
    await purge(storage)
    assert f"recordings/{run.id}.wav" in storage.objects
    await async_session.refresh(run)
    assert run.extra == first_extra


async def test_run_is_retried_when_storage_delete_fails(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    run = await make_run(async_session, storage, data.workflow, 120)
    await async_session.commit()
    storage.failing.add(f"transcripts/{run.id}.txt")

    result = await purge(storage)

    assert result.runs_deferred >= 1
    await async_session.refresh(run)
    assert "purged_at" not in run.extra
    assert run.transcript_url == f"transcripts/{run.id}.txt"

    storage.failing.clear()
    await purge(storage)
    await async_session.refresh(run)
    assert "purged_at" in run.extra
    assert storage.objects.isdisjoint(run_keys(run.id))


async def make_campaign(session, data, *, state, age_days, source_id=None):
    created = NOW - timedelta(days=age_days)
    campaign = CampaignModel(
        name="Spring calls",
        organization_id=data.org.id,
        workflow_id=data.workflow.id,
        created_by=data.user.id,
        source_type="csv",
        source_id=source_id or f"campaigns/{data.org.id}/{uuid.uuid4()}_list.csv",
        state=state,
        created_at=created,
        last_activity_at=created,
        completed_at=created if state == "completed" else None,
    )
    session.add(campaign)
    await session.flush()
    queued = QueuedRunModel(
        campaign_id=campaign.id,
        source_uuid=f"row-{uuid.uuid4().hex}",
        context_variables={"phone_number": "+353870000002", "first_name": "Cian"},
        state="processed",
        created_at=created,
    )
    session.add(queued)
    await session.flush()
    return campaign, queued


async def test_expired_campaign_csv_and_contact_rows_are_deleted(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    done, done_row = await make_campaign(
        async_session, data, state="completed", age_days=100
    )
    idle, idle_row = await make_campaign(
        async_session, data, state="paused", age_days=100
    )
    recent, recent_row = await make_campaign(
        async_session, data, state="completed", age_days=10
    )
    storage.add(done.source_id, idle.source_id, recent.source_id)
    await async_session.commit()

    await purge(storage)

    assert done.source_id not in storage.objects
    assert idle.source_id not in storage.objects
    assert recent.source_id in storage.objects
    for row, cleared in ((done_row, True), (idle_row, True), (recent_row, False)):
        await async_session.refresh(row)
        assert (row.context_variables == {}) is cleared
    await async_session.refresh(idle)
    assert idle.state == "failed"
    assert idle.logs[-1]["event"] == "retention_expired"
    await async_session.refresh(done)
    assert "retention_purged_at" in done.orchestrator_metadata


async def test_shared_campaign_csv_waits_for_the_last_campaign(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    parent, _ = await make_campaign(
        async_session, data, state="completed", age_days=100
    )
    child, _ = await make_campaign(
        async_session, data, state="running", age_days=100, source_id=parent.source_id
    )
    storage.add(parent.source_id)
    await async_session.commit()

    await purge(storage)

    # The redial child still uses the list.
    assert parent.source_id in storage.objects
    await async_session.refresh(parent)
    assert "retention_purged_at" in parent.orchestrator_metadata


@pytest.mark.parametrize("state", ["syncing", "running", "paused"])
async def test_rows_of_an_active_campaign_are_kept(
    db_session, async_session, storage, state
):
    data = await make_org(async_session)
    campaign, old_row = await make_campaign(
        async_session, data, state=state, age_days=100
    )
    # Still in use: the campaign was active yesterday.
    campaign.last_activity_at = NOW - timedelta(days=1)
    waiting = QueuedRunModel(
        campaign_id=campaign.id,
        source_uuid="row-waiting",
        context_variables={"phone_number": "+353870000003"},
        state="queued",
        created_at=NOW - timedelta(days=100),
    )
    async_session.add(waiting)
    storage.add(campaign.source_id)
    await async_session.commit()

    await purge(storage)

    # The dispatcher and its retries still read these rows.
    await async_session.refresh(old_row)
    await async_session.refresh(waiting)
    assert old_row.context_variables == {
        "phone_number": "+353870000002",
        "first_name": "Cian",
    }
    assert waiting.context_variables == {"phone_number": "+353870000003"}
    assert campaign.source_id in storage.objects


async def test_recently_finished_campaign_keeps_rows_for_redial(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    campaign, old_row = await make_campaign(
        async_session, data, state="completed", age_days=100
    )
    campaign.completed_at = NOW - timedelta(days=10)
    storage.add(campaign.source_id)
    await async_session.commit()

    await purge(storage)

    await async_session.refresh(old_row)
    assert old_row.context_variables["phone_number"] == "+353870000002"
    assert campaign.source_id in storage.objects


async def test_rows_of_a_finished_campaign_are_cleared_when_its_csv_is_deferred(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    campaign, row = await make_campaign(
        async_session, data, state="completed", age_days=100
    )
    storage.add(campaign.source_id)
    storage.failing.add(campaign.source_id)
    await async_session.commit()

    result = await purge(storage)

    assert result.campaigns_deferred >= 1
    await async_session.refresh(campaign)
    await async_session.refresh(row)
    assert "retention_purged_at" not in campaign.orchestrator_metadata
    assert row.context_variables == {}


async def test_campaign_csv_is_kept_when_the_campaign_turns_active(
    db_session, async_session, storage, monkeypatch
):
    data = await make_org(async_session)
    campaign, row = await make_campaign(
        async_session, data, state="running", age_days=100
    )
    storage.add(campaign.source_id)
    await async_session.commit()

    # The campaign looked idle when listed, then was resumed before the scrub.
    async def stale_listing(*, organization_id, after_id, **_kwargs):
        if organization_id != data.org.id or after_id:
            return []
        return [
            ExpiredCampaign(
                id=campaign.id,
                state="paused",
                source_type="csv",
                source_id=campaign.source_id,
            )
        ]

    monkeypatch.setattr(db_client, "get_campaigns_past_retention", stale_listing)

    await purge(storage)

    assert campaign.source_id in storage.objects
    await async_session.refresh(campaign)
    await async_session.refresh(row)
    assert campaign.state == "running"
    assert "retention_purged_at" not in campaign.orchestrator_metadata
    assert row.context_variables["phone_number"] == "+353870000002"


async def test_ongoing_text_chat_is_not_purged(db_session, async_session, storage):
    data = await make_org(async_session)
    ongoing = await make_run(
        async_session,
        storage,
        data.workflow,
        120,
        text_session=True,
        completed=False,
        chat_updated_days_ago=0,
    )
    abandoned = await make_run(
        async_session, storage, data.workflow, 120, text_session=True, completed=False
    )
    await async_session.commit()

    await purge(storage)

    await async_session.refresh(ongoing)
    await async_session.refresh(abandoned)
    assert "purged_at" not in ongoing.extra
    assert run_keys(ongoing.id) <= storage.objects
    assert "purged_at" in abandoned.extra
    assert storage.objects.isdisjoint(run_keys(abandoned.id))


async def test_invalid_stored_retention_skips_the_organization(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    await async_session.commit()
    await set_retention(db_session, data.org.id, "forever")
    run = await make_run(async_session, storage, data.workflow, 400)
    await async_session.commit()

    messages = []
    sink = logger.add(messages.append, level="ERROR")
    try:
        result = await purge(storage)
    finally:
        logger.remove(sink)

    assert result.organizations_skipped >= 1
    assert run_keys(run.id) <= storage.objects
    await async_session.refresh(run)
    assert "purged_at" not in run.extra
    assert any(
        f"skipped organization {data.org.id}:" in message for message in messages
    )


async def test_unrelated_invalid_preference_keeps_the_chosen_period(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    await async_session.commit()
    await db_session.upsert_configuration(
        data.org.id,
        OrganizationConfigurationKey.ORGANIZATION_PREFERENCES.value,
        {"call_data_retention_days": 365, "disposition_mapping": "broken"},
    )
    run = await make_run(async_session, storage, data.workflow, 200)
    await async_session.commit()

    await purge(storage)

    await async_session.refresh(run)
    assert "purged_at" not in run.extra
    assert run_keys(run.id) <= storage.objects


async def test_deferred_runs_are_summarized_per_organization(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    runs = [
        await make_run(async_session, storage, data.workflow, 120) for _ in range(2)
    ]
    await async_session.commit()
    for run in runs:
        storage.failing.add(f"transcripts/{run.id}.txt")

    messages = []
    sink = logger.add(messages.append, level="ERROR")
    try:
        await purge(storage)
    finally:
        logger.remove(sink)

    summaries = [
        message
        for message in messages
        if f"deferred 2 runs of organization {data.org.id}:" in message
    ]
    assert len(summaries) == 1


async def test_dry_run_changes_nothing_and_logs_counts(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    run = await make_run(async_session, storage, data.workflow, 120)
    campaign, row = await make_campaign(
        async_session, data, state="completed", age_days=100
    )
    storage.add(campaign.source_id)
    token = EmbedTokenModel(
        token=f"tok-{uuid.uuid4().hex}",
        workflow_id=data.workflow.id,
        organization_id=data.org.id,
        created_by=data.user.id,
    )
    async_session.add(token)
    await async_session.flush()
    visitor = EmbedSessionModel(
        session_token=f"sess-{uuid.uuid4().hex}",
        embed_token_id=token.id,
        client_ip="198.51.100.7",
        user_agent="Mozilla/5.0",
        created_at=NOW - timedelta(days=31),
        expires_at=NOW - timedelta(days=31) + timedelta(hours=1),
    )
    delivery = WebhookDeliveryModel(
        workflow_run_id=run.id,
        organization_id=data.org.id,
        endpoint_url="https://example.com/hook",
        payload={"caller": "+353870000001"},
        webhook_node_id="a",
        status="succeeded",
        created_at=NOW - timedelta(days=31),
    )
    async_session.add_all([visitor, delivery])
    await async_session.commit()
    before = set(storage.objects)

    messages = []
    sink = logger.add(messages.append, level="INFO")
    try:
        result = await purge_expired_data(
            now=NOW, resolve_storage=lambda _backend: storage, dry_run=True
        )
    finally:
        logger.remove(sink)

    assert storage.objects == before
    assert result.runs_purged == result.campaigns_purged == 0
    assert result.embed_sessions_cleared == result.webhook_deliveries_cleared == 0
    for obj in (run, campaign, row, visitor, delivery):
        await async_session.refresh(obj)
    assert "purged_at" not in run.extra
    assert "retention_purged_at" not in campaign.orchestrator_metadata
    assert row.context_variables["phone_number"] == "+353870000002"
    assert visitor.client_ip == "198.51.100.7"
    assert delivery.payload == {"caller": "+353870000001"}
    [line] = [m for m in messages if f"organization={data.org.id} " in m]
    assert line.rstrip().endswith(
        f"Retention purge dry run: organization={data.org.id} runs=1 "
        "campaigns=1 queued_rows=1 widget_sessions=1 webhook_deliveries=1 "
        "archived_documents=0 archived_recordings=0"
    )
    # Counts only: nothing personal reaches the log.
    assert "+353" not in line and "198.51.100.7" not in line


async def test_cron_does_nothing_when_disabled(monkeypatch):
    calls = []

    async def fake_purge(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(retention_purge, "purge_expired_data", fake_purge)
    monkeypatch.setattr(retention_purge.constants, "RETENTION_PURGE_ENABLED", False)
    await retention_purge.purge_expired_data_daily({})
    assert calls == []

    monkeypatch.setattr(retention_purge.constants, "RETENTION_PURGE_ENABLED", True)
    monkeypatch.setattr(retention_purge.constants, "RETENTION_PURGE_DRY_RUN", True)
    await retention_purge.purge_expired_data_daily({})
    assert calls == [{"dry_run": True}]


async def test_visitor_data_and_webhook_payloads_cleared_after_30_days(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    run = await make_run(async_session, storage, data.workflow, 5)
    token = EmbedTokenModel(
        token=f"tok-{uuid.uuid4().hex}",
        workflow_id=data.workflow.id,
        organization_id=data.org.id,
        created_by=data.user.id,
    )
    async_session.add(token)
    await async_session.flush()

    def embed_session(age_days):
        return EmbedSessionModel(
            session_token=f"sess-{uuid.uuid4().hex}",
            embed_token_id=token.id,
            client_ip="198.51.100.7",
            user_agent="Mozilla/5.0",
            origin="https://lightmove.ai",
            created_at=NOW - timedelta(days=age_days),
            expires_at=NOW - timedelta(days=age_days) + timedelta(hours=1),
        )

    old_session, new_session = embed_session(31), embed_session(29)

    def delivery(node, status, age_days):
        return WebhookDeliveryModel(
            workflow_run_id=run.id,
            organization_id=data.org.id,
            endpoint_url="https://example.com/hook",
            payload={"caller": "+353870000001"},
            last_error="HTTP 500: {'caller': '+353870000001'}",
            webhook_node_id=node,
            status=status,
            created_at=NOW - timedelta(days=age_days),
        )

    old_done = delivery("a", "succeeded", 31)
    old_dead = delivery("b", "dead_letter", 31)
    old_pending = delivery("c", "pending", 31)
    new_done = delivery("d", "succeeded", 29)
    async_session.add_all(
        [old_session, new_session, old_done, old_dead, old_pending, new_done]
    )
    await async_session.commit()

    result = await purge(storage)
    assert result.embed_sessions_cleared >= 1
    assert result.webhook_deliveries_cleared >= 2

    for row in (old_session, new_session, old_done, old_dead, old_pending, new_done):
        await async_session.refresh(row)
    assert (old_session.client_ip, old_session.user_agent) == (None, None)
    assert old_session.origin == "https://lightmove.ai"
    assert new_session.client_ip == "198.51.100.7"
    for row in (old_done, old_dead):
        assert row.payload == {}
        assert row.last_error is None
        assert row.endpoint_url == "https://example.com/hook"
    # A pending delivery still needs its payload; recent ones are kept.
    assert old_pending.payload == {"caller": "+353870000001"}
    assert new_done.payload == {"caller": "+353870000001"}

    # Nothing left to clear for these rows on the next pass.
    await purge(storage)
    await async_session.refresh(old_done)
    assert old_done.payload == {}


def test_purge_runs_daily_off_peak():
    from api.tasks.arq import WorkerSettings
    from api.tasks.retention_purge import purge_expired_data_daily

    [job] = [
        job
        for job in WorkerSettings.cron_jobs
        if job.coroutine is purge_expired_data_daily
    ]
    assert (job.hour, job.minute, job.second) == (3, 17, 0)
    assert job.unique
