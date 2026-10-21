"""Organisation deletion: request, cancel, the closed API and the erasure cron."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import func, select

from api import constants
from api.db.models import (
    AgentTriggerModel,
    APIKeyModel,
    BillingAccountModel,
    BillingLedgerEntryModel,
    CampaignModel,
    EmbedSessionModel,
    EmbedTokenModel,
    ExternalCredentialModel,
    FolderModel,
    IntegrationModel,
    KnowledgeBaseChunkModel,
    KnowledgeBaseDocumentModel,
    OrganizationConfigurationModel,
    OrganizationInvitationModel,
    OrganizationModel,
    OrganizationUsageCycleModel,
    QueuedRunModel,
    TelephonyConfigurationModel,
    TelephonyPhoneNumberModel,
    ToolModel,
    UserModel,
    WebhookDeliveryModel,
    WorkflowDefinitionModel,
    WorkflowModel,
    WorkflowRecordingModel,
    WorkflowRunModel,
    WorkflowRunTextSessionModel,
    organization_users_association,
)
from api.db.org_erasure_client import ERASED_ORGANIZATION_NAME
from api.db.skill_models import SkillModel
from api.enums import OrgRole
from api.errors.privacy import OrganizationErasedError
from api.errors.telephony_errors import TelephonyError
from api.services.privacy import org_deletion, org_erasure
from api.services.privacy.org_erasure import erase_deleted_organizations
from api.services.quota_service import authorize_workflow_run_start
from api.tasks import org_erasure as org_erasure_task
from api.tests.support.privacy_seed import (
    FakeStorage,
    add_member,
    make_user,
    run_object_keys,
    seed_organization,
)

pytestmark = pytest.mark.real_org_roles

NOW = datetime(2026, 10, 21, 3, 47, tzinfo=UTC)
ORG_SCOPED_MODELS = (
    APIKeyModel,
    EmbedTokenModel,
    AgentTriggerModel,
    CampaignModel,
    TelephonyConfigurationModel,
    TelephonyPhoneNumberModel,
    WorkflowModel,
    WorkflowRecordingModel,
    FolderModel,
    IntegrationModel,
    ToolModel,
    ExternalCredentialModel,
    KnowledgeBaseDocumentModel,
    KnowledgeBaseChunkModel,
    SkillModel,
    OrganizationConfigurationModel,
    OrganizationInvitationModel,
    WebhookDeliveryModel,
)


@pytest.fixture
def storage():
    return FakeStorage()


async def count(session, model, **where) -> int:
    query = select(func.count()).select_from(model)
    for column, value in where.items():
        query = query.where(getattr(model, column) == value)
    return (await session.execute(query)).scalar_one()


async def seeded(async_session, storage, **kwargs):
    data = await seed_organization(async_session, storage, **kwargs)
    await async_session.commit()
    return data


async def schedule(db_session, org_id, *, days_ago=31):
    requested = NOW - timedelta(days=days_ago)
    await db_session.request_organization_deletion(
        org_id, requested_at=requested, scheduled_for=requested + timedelta(days=30)
    )


async def erase(storage, now=NOW):
    return await erase_deleted_organizations(
        now=now, resolve_storage=lambda _backend: storage
    )


# --- request and cancel -------------------------------------------------------


async def test_request_switches_off_and_cancel_restores_only_that(
    db_session, async_session, storage
):
    data = await seeded(async_session, storage)

    state = await org_deletion.request_organization_deletion(
        data.org.id, confirm_name="  acme ltd ", now=NOW
    )
    assert state.is_pending
    assert state.scheduled_for == NOW + timedelta(days=30)

    for row in (
        data.api_key,
        data.embed_token,
        data.trigger,
        data.campaign,
        data.disabled_api_key,
        data.disabled_embed_token,
        data.archived_trigger,
        data.finished_campaign,
    ):
        await async_session.refresh(row)
    assert data.api_key.is_active is False
    assert data.embed_token.is_active is False
    assert data.trigger.state == "archived"
    assert data.campaign.state == "paused"
    assert data.finished_campaign.state == "completed"

    # A second request keeps the first schedule.
    again = await org_deletion.request_organization_deletion(
        data.org.id, confirm_name="Acme Ltd", now=NOW + timedelta(days=3)
    )
    assert again.scheduled_for == NOW + timedelta(days=30)

    await org_deletion.cancel_organization_deletion(
        data.org.id, now=NOW + timedelta(days=5)
    )
    for row in (
        data.api_key,
        data.embed_token,
        data.trigger,
        data.campaign,
        data.disabled_api_key,
        data.disabled_embed_token,
        data.archived_trigger,
        data.org,
    ):
        await async_session.refresh(row)
    assert data.api_key.is_active is True
    assert data.embed_token.is_active is True
    assert data.trigger.state == "active"
    assert data.campaign.state == "running"
    # What was already off before the request stays off.
    assert data.disabled_api_key.is_active is False
    assert data.disabled_embed_token.is_active is False
    assert data.archived_trigger.state == "archived"
    assert data.org.deletion_requested_at is None
    assert data.org.deletion_suspended is None


async def test_cancel_after_the_grace_period_is_refused(
    db_session, async_session, storage
):
    data = await seeded(async_session, storage)
    await schedule(db_session, data.org.id)
    with pytest.raises(Exception) as exc:
        await org_deletion.cancel_organization_deletion(data.org.id, now=NOW)
    assert getattr(exc.value, "code", None) == "organization_erasure_started"


# --- the API while pending ------------------------------------------------------


async def test_request_requires_the_exact_name(
    db_session, async_session, storage, test_client_factory
):
    data = await seeded(async_session, storage)
    async with test_client_factory(data.admin) as client:
        response = await client.post(
            "/api/v1/organizations/deletion", json={"confirm_name": "Acme"}
        )
    assert response.status_code == 400
    assert response.json()["code"] == "confirmation_mismatch"
    await async_session.refresh(data.org)
    assert data.org.deletion_requested_at is None


@pytest.mark.parametrize("role", [OrgRole.DEVELOPER, OrgRole.VIEWER])
async def test_only_admins_can_delete_or_cancel(
    db_session, async_session, storage, test_client_factory, role
):
    data = await seeded(async_session, storage)
    member = await make_user(async_session, data.org)
    await add_member(async_session, member, data.org, role)
    await async_session.commit()

    async with test_client_factory(member) as client:
        request = await client.post(
            "/api/v1/organizations/deletion", json={"confirm_name": "Acme Ltd"}
        )
        export = await client.get("/api/v1/organizations/export")
    assert request.status_code == 403
    assert export.status_code == 403

    await schedule(db_session, data.org.id, days_ago=1)
    async with test_client_factory(member) as client:
        cancel = await client.delete("/api/v1/organizations/deletion")
        status = await client.get("/api/v1/organizations/deletion")
    assert cancel.status_code == 403
    # Every member can see that the organisation is going away.
    assert status.status_code == 200
    assert status.json()["pending"] is True


async def test_pending_organization_api_is_closed_except_the_way_out(
    db_session, async_session, storage, test_client_factory
):
    data = await seeded(async_session, storage)
    async with test_client_factory(data.admin) as client:
        assert (await client.get("/api/v1/organizations/members")).status_code == 200

        response = await client.post(
            "/api/v1/organizations/deletion", json={"confirm_name": "Acme Ltd"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["pending"] is True
        assert body["scheduled_for"]

        blocked = await client.get("/api/v1/organizations/members")
        assert blocked.status_code == 423
        assert blocked.json()["code"] == "organization_pending_deletion"
        assert blocked.json()["deletion_scheduled_for"]
        assert (
            await client.get("/api/v1/organizations/telephony-config-warnings")
        ).status_code == 423

        # Still open: export, status, the user's own endpoints, the context.
        assert (await client.get("/api/v1/organizations/export")).status_code == 200
        assert (await client.get("/api/v1/organizations/deletion")).status_code == 200
        assert (await client.get("/api/v1/user/me/export")).status_code == 200
        assert (await client.get("/api/v1/user/auth/user")).status_code == 200
        assert (await client.get("/api/v1/organizations/mine")).status_code == 200
        context = await client.get("/api/v1/organizations/context")
        assert context.status_code == 200
        assert context.json()["deletion"]["pending"] is True

        cancel = await client.delete("/api/v1/organizations/deletion")
        assert cancel.status_code == 200
        assert cancel.json() == {
            "pending": False,
            "requested_at": None,
            "scheduled_for": None,
        }
        assert (await client.get("/api/v1/organizations/members")).status_code == 200
        context = await client.get("/api/v1/organizations/context")
        assert context.json()["deletion"] is None

        again = await client.delete("/api/v1/organizations/deletion")
        assert again.status_code == 409


async def test_pending_organization_starts_no_calls(db_session, async_session, storage):
    data = await seeded(async_session, storage)
    await schedule(db_session, data.org.id, days_ago=1)

    result = await authorize_workflow_run_start(
        workflow_id=data.workflow.id, organization_id=data.org.id
    )
    assert result.has_quota is False
    assert result.error_code == "organization_pending_deletion"


async def test_inbound_call_to_pending_organization_is_refused(
    db_session, async_session, storage
):
    from api.routes.telephony import handle_inbound_run

    data = await seeded(async_session, storage)
    await schedule(db_session, data.org.id, days_ago=1)

    request = SimpleNamespace(headers={}, url="https://api.example.test/inbound/run")
    provider_class = SimpleNamespace(
        PROVIDER_NAME="twilio",
        generate_validation_error_response=Mock(return_value="refused"),
    )
    normalized = SimpleNamespace(
        provider="twilio",
        direction="inbound",
        to_number="+35315550100",
        from_number="+353870000009",
        to_country="IE",
        from_country="IE",
        account_id="AC123",
        call_id="CA1",
        raw_data={},
    )
    config = SimpleNamespace(
        id=1, organization_id=data.org.id, name="Twilio", credentials={}
    )
    phone_row = SimpleNamespace(
        id=data.phone_number.id,
        address="+35315550100",
        inbound_workflow_id=data.workflow.id,
    )
    create_run = AsyncMock(return_value=1)
    with (
        patch(
            "api.routes.telephony.parse_webhook_request",
            new=AsyncMock(return_value=({}, "")),
        ),
        patch(
            "api.routes.telephony._detect_provider",
            new=AsyncMock(return_value=provider_class),
        ),
        patch("api.routes.telephony.normalize_webhook_data", return_value=normalized),
        patch(
            "api.routes.telephony.db_client.find_inbound_route_by_account",
            new=AsyncMock(return_value=(config, phone_row)),
        ),
        patch("api.routes.telephony._create_inbound_workflow_run", new=create_run),
    ):
        response = await handle_inbound_run(request)

    assert response == "refused"
    provider_class.generate_validation_error_response.assert_called_once_with(
        TelephonyError.ORGANIZATION_UNAVAILABLE
    )
    create_run.assert_not_awaited()


# --- erasure --------------------------------------------------------------------


async def test_erasure_deletes_everything_but_billing_and_leaves_a_tombstone(
    db_session, async_session, storage
):
    data = await seeded(async_session, storage)
    other = await seeded(async_session, storage, name="Other Co")
    # A member of both keeps their account and their other organisation.
    await add_member(async_session, data.admin, other.org, OrgRole.DEVELOPER)
    await async_session.commit()
    original_provider_id = data.org.provider_id
    await schedule(db_session, data.org.id)

    result = await erase(storage)

    assert result.organizations_erased == 1
    assert result.organizations_deferred == 0

    # Storage: exactly this organisation's objects, never the other one's.
    assert storage.objects.isdisjoint(data.objects)
    assert other.objects <= storage.objects
    assert set(storage.deleted_prefixes) == {
        f"recordings/{data.run.id}/noveum/",
        f"campaigns/{data.org.id}/",
        f"knowledge_base/{data.org.id}/",
        f"ambient-noise/{data.org.id}/",
    }
    expected_files = run_object_keys(data.run.id) - {
        f"recordings/{data.run.id}/noveum/user/seg-1.wav"
    } | {f"recordings/{data.org.id}/Greet0001/greeting.wav"}
    assert set(storage.deleted_files) == expected_files

    # Rows: nothing of the organisation is left.
    org_id = data.org.id
    for model in ORG_SCOPED_MODELS:
        assert await count(async_session, model, organization_id=org_id) == 0, model
    assert await count(async_session, WorkflowRunModel, id=data.run.id) == 0
    assert (
        await count(
            async_session, WorkflowRunTextSessionModel, workflow_run_id=data.run.id
        )
        == 0
    )
    assert (
        await count(async_session, EmbedSessionModel, workflow_run_id=data.run.id) == 0
    )
    assert await count(async_session, QueuedRunModel, campaign_id=data.campaign.id) == 0
    assert (
        await count(
            async_session, WorkflowDefinitionModel, workflow_id=data.workflow.id
        )
        == 0
    )
    members = await async_session.execute(
        select(func.count())
        .select_from(organization_users_association)
        .where(organization_users_association.c.organization_id == org_id)
    )
    assert members.scalar_one() == 0

    # Accounting records survive.
    assert await count(async_session, BillingAccountModel, organization_id=org_id) == 1
    ledger = (
        await async_session.execute(
            select(BillingLedgerEntryModel).where(
                BillingLedgerEntryModel.id == data.ledger_entry.id
            )
        )
    ).scalar_one()
    await async_session.refresh(ledger)
    assert ledger.workflow_run_id is None
    assert str(ledger.amount_eur) == "-1.2000"
    assert (
        await count(async_session, OrganizationUsageCycleModel, organization_id=org_id)
        == 1
    )

    # Tombstone.
    org = (
        await async_session.execute(
            select(OrganizationModel).where(OrganizationModel.id == org_id)
        )
    ).scalar_one()
    await async_session.refresh(org)
    assert org.name == ERASED_ORGANIZATION_NAME
    assert org.provider_id == f"deleted_{org_id}"
    assert org.erased_provider_id == original_provider_id
    assert org.erased_at == NOW

    # Members keep their accounts: one with another organisation moves to
    # it, one without is left with none.
    await async_session.refresh(data.admin)
    assert data.admin.selected_organization_id == other.org.id
    await async_session.refresh(data.developer)
    assert data.developer.selected_organization_id is None
    assert await count(async_session, UserModel, id=data.admin.id) == 1

    # The other organisation is untouched.
    await async_session.refresh(other.org)
    assert other.org.erased_at is None
    assert await count(async_session, WorkflowRunModel, id=other.run.id) == 1
    assert await count(async_session, ToolModel, organization_id=other.org.id) == 1

    # The provider id can never bring the organisation back.
    with pytest.raises(OrganizationErasedError):
        await db_session.get_or_create_organization_by_provider_id(
            org_provider_id=original_provider_id, user_id=data.admin.id
        )


async def test_erasure_is_idempotent(db_session, async_session, storage):
    data = await seeded(async_session, storage)
    await schedule(db_session, data.org.id)
    await erase(storage)

    storage.deleted_files.clear()
    storage.deleted_prefixes.clear()
    result = await erase(storage, now=NOW + timedelta(days=1))

    assert result.organizations_erased == 0
    assert storage.deleted_files == []
    assert storage.deleted_prefixes == []


async def test_organizations_not_yet_due_are_untouched(
    db_session, async_session, storage
):
    data = await seeded(async_session, storage)
    await schedule(db_session, data.org.id, days_ago=29)

    result = await erase(storage)

    assert result.organizations_erased == 0
    assert data.objects <= storage.objects
    assert await count(async_session, WorkflowRunModel, id=data.run.id) == 1
    await async_session.refresh(data.org)
    assert data.org.erased_at is None


async def test_storage_failure_defers_and_the_next_pass_resumes(
    db_session, async_session, storage
):
    data = await seeded(async_session, storage)
    await schedule(db_session, data.org.id)
    recording_key = f"recordings/{data.org.id}/Greet0001/greeting.wav"
    storage.failing.add(recording_key)

    result = await erase(storage)

    assert result.organizations_deferred == 1
    # Runs went first; the rows that name the failed object stay.
    assert await count(async_session, WorkflowRunModel, id=data.run.id) == 0
    assert (
        await count(async_session, WorkflowRecordingModel, organization_id=data.org.id)
        == 1
    )
    await async_session.refresh(data.org)
    assert data.org.erased_at is None

    storage.failing.clear()
    result = await erase(storage, now=NOW + timedelta(days=1))
    assert result.organizations_erased == 1
    assert storage.objects.isdisjoint(data.objects)


async def test_prompt_recording_keys_outside_the_organization_are_not_deleted(
    db_session, async_session, storage
):
    data = await seeded(async_session, storage)
    foreign = WorkflowRecordingModel(
        recording_id="Evil0001",
        organization_id=data.org.id,
        transcript="x",
        storage_key=f"knowledge_base/{data.org.id + 1}/doc/secret.pdf",
        storage_backend="minio",
    )
    async_session.add(foreign)
    await async_session.commit()
    storage.add(foreign.storage_key)
    await schedule(db_session, data.org.id)

    await erase(storage)

    assert foreign.storage_key in storage.objects
    assert foreign.storage_key not in storage.deleted_files


async def test_erasure_deletes_the_stack_team(
    db_session, async_session, storage, monkeypatch
):
    data = await seeded(async_session, storage)
    team_id = data.org.provider_id
    await schedule(db_session, data.org.id)
    delete_team = AsyncMock()
    monkeypatch.setattr(constants, "AUTH_PROVIDER", "stack")
    monkeypatch.setattr(org_erasure.stackauth, "delete_team", delete_team)

    await erase(storage)

    delete_team.assert_awaited_once_with(team_id)


async def test_cron_respects_the_kill_switch(monkeypatch):
    calls = []

    async def fake_erase():
        calls.append(True)

    monkeypatch.setattr(org_erasure_task, "erase_deleted_organizations", fake_erase)
    monkeypatch.setattr(org_erasure_task.constants, "ORG_ERASURE_ENABLED", False)
    await org_erasure_task.erase_deleted_organizations_daily({})
    assert calls == []

    monkeypatch.setattr(org_erasure_task.constants, "ORG_ERASURE_ENABLED", True)
    await org_erasure_task.erase_deleted_organizations_daily({})
    assert calls == [True]


def test_erasure_runs_daily_after_the_retention_purge():
    from api.tasks.arq import WorkerSettings

    [job] = [
        job
        for job in WorkerSettings.cron_jobs
        if job.coroutine is org_erasure_task.erase_deleted_organizations_daily
    ]
    assert (job.hour, job.minute, job.second) == (3, 47, 0)


# --- review follow-ups ------------------------------------------------------


async def test_syncing_campaigns_are_paused_and_their_sync_does_not_start_them(
    db_session, async_session, storage
):
    data = await seeded(async_session, storage)
    synced_meanwhile = CampaignModel(
        name="Syncing, finishes while pending",
        organization_id=data.org.id,
        workflow_id=data.workflow.id,
        source_type="csv",
        source_id=f"campaigns/{data.org.id}/a.csv",
        state="syncing",
        source_sync_status="in_progress",
    )
    still_syncing = CampaignModel(
        name="Syncing, still syncing at cancel",
        organization_id=data.org.id,
        workflow_id=data.workflow.id,
        source_type="csv",
        source_id=f"campaigns/{data.org.id}/b.csv",
        state="syncing",
        source_sync_status="in_progress",
    )
    async_session.add_all([synced_meanwhile, still_syncing])
    await async_session.commit()

    await org_deletion.request_organization_deletion(
        data.org.id, confirm_name="Acme Ltd", now=NOW
    )
    for campaign in (synced_meanwhile, still_syncing, data.campaign):
        await async_session.refresh(campaign)
        assert campaign.state == "paused"

    # The sync job finishing while paused records the sync, not a start.
    started = await db_session.complete_campaign_source_sync(
        synced_meanwhile.id, synced_at=NOW
    )
    assert started is False
    await async_session.refresh(synced_meanwhile)
    assert synced_meanwhile.state == "paused"
    assert synced_meanwhile.source_sync_status == "completed"

    await org_deletion.cancel_organization_deletion(
        data.org.id, now=NOW + timedelta(days=1)
    )
    for campaign in (synced_meanwhile, still_syncing, data.campaign):
        await async_session.refresh(campaign)
    assert synced_meanwhile.state == "running"
    assert still_syncing.state == "syncing"
    assert data.campaign.state == "running"


async def test_completed_sync_starts_an_unpaused_campaign(
    db_session, async_session, storage
):
    data = await seeded(async_session, storage)
    data.campaign.state = "syncing"
    await async_session.commit()
    assert await db_session.complete_campaign_source_sync(
        data.campaign.id, synced_at=NOW
    )
    await async_session.refresh(data.campaign)
    assert data.campaign.state == "running"


async def test_dispatcher_claims_no_contacts_for_a_pending_organization(
    db_session, async_session, storage, monkeypatch
):
    from api.services.campaign.campaign_call_dispatcher import (
        campaign_call_dispatcher,
    )

    data = await seeded(async_session, storage)
    await schedule(db_session, data.org.id, days_ago=1)
    # Even a campaign that is (somehow) running dials nobody.
    data.campaign.state = "running"
    await async_session.commit()
    claim = AsyncMock(return_value=[])
    monkeypatch.setattr(db_session, "claim_queued_runs_for_processing", claim)

    assert await campaign_call_dispatcher.process_batch(data.campaign.id) == 0
    claim.assert_not_awaited()


async def test_agent_stream_refuses_a_pending_organization_before_creating_a_run():
    from api.routes.agent_stream import agent_stream_websocket

    websocket = SimpleNamespace(query_params={}, accept=AsyncMock(), close=AsyncMock())
    workflow = SimpleNamespace(id=1, user_id=None, organization_id=5)
    with (
        patch("api.routes.agent_stream.telephony_registry") as registry,
        patch("api.routes.agent_stream.db_client") as db,
        patch(
            "api.routes.agent_stream.organization_accepts_calls",
            new=AsyncMock(return_value=False),
        ),
    ):
        registry.get_optional.return_value = SimpleNamespace()
        db.get_workflow_by_uuid_unscoped = AsyncMock(return_value=workflow)
        db.create_workflow_run = AsyncMock()
        await agent_stream_websocket(websocket, "cloudonix", "agent-uuid")

    db.create_workflow_run.assert_not_awaited()
    websocket.close.assert_awaited_once()


async def test_erasure_erases_the_tools_service_data(
    db_session, async_session, storage, monkeypatch
):
    from api.services.tool_integrations.client import ToolsServiceClient

    data = await seeded(async_session, storage)
    await schedule(db_session, data.org.id)
    monkeypatch.setattr(constants, "TOOLS_INTERNAL_SECRET", "s" * 20)
    erase_tools = AsyncMock(return_value={"connections": 2})
    monkeypatch.setattr(ToolsServiceClient, "erase_organization", erase_tools)

    result = await erase(storage)

    assert result.organizations_erased == 1
    erase_tools.assert_awaited_once_with(data.org.id)


async def test_tools_service_failure_defers_erasure(
    db_session, async_session, storage, monkeypatch
):
    from api.errors.integrations import ToolsServiceUnavailableError
    from api.services.tool_integrations.client import ToolsServiceClient

    data = await seeded(async_session, storage)
    await schedule(db_session, data.org.id)
    monkeypatch.setattr(constants, "TOOLS_INTERNAL_SECRET", "s" * 20)
    monkeypatch.setattr(
        ToolsServiceClient,
        "erase_organization",
        AsyncMock(side_effect=ToolsServiceUnavailableError()),
    )

    result = await erase(storage)

    assert result.organizations_deferred == 1
    await async_session.refresh(data.org)
    assert data.org.erased_at is None
    assert await count(async_session, ToolModel, organization_id=data.org.id) == 1


async def test_tools_service_client_sends_no_user_for_erasure():
    import httpx

    from api.services.tool_integrations.client import ToolsServiceClient

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        seen["method"], seen["path"] = request.method, request.url.path
        return httpx.Response(200, json={"connections": 1, "note": "x"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = ToolsServiceClient(
            base_url="http://tools.test", internal_secret="secret", http=http
        )
        assert await client.erase_organization(7) == {"connections": 1}
    assert (seen["method"], seen["path"]) == ("DELETE", "/internal/org")
    assert seen["x-org-id"] == "7"
    assert "x-user-id" not in seen


async def test_organization_prefixes_are_deleted_on_every_configured_backend(
    db_session, async_session, storage, monkeypatch
):
    data = await seeded(async_session, storage)
    old_backend = FakeStorage()
    old_backend.add(f"knowledge_base/{data.org.id}/old/doc.pdf")
    await schedule(db_session, data.org.id)
    monkeypatch.setattr(
        org_erasure, "configured_storage_backends", lambda: ["minio", "s3"]
    )

    await erase_deleted_organizations(
        now=NOW,
        resolve_storage=lambda backend: old_backend if backend == "s3" else storage,
    )

    assert old_backend.objects == set()
    assert set(old_backend.deleted_prefixes) == {
        f"campaigns/{data.org.id}/",
        f"knowledge_base/{data.org.id}/",
        f"ambient-noise/{data.org.id}/",
    }


@pytest.mark.parametrize(
    ("recording_id", "key", "ok"),
    [
        ("Greet0001", "recordings/7/Greet0001/greeting.wav", True),
        ("Greet0001", "recordings/7/Greet0001/nested/take 2.wav", True),
        ("Greet0001", "recordings/7/Greet0001/", False),
        ("Greet0001", "recordings/7/Greet0001/../../12.wav", False),
        ("Greet0001", "recordings/8/Greet0001/greeting.wav", False),
        ("Greet0001", "knowledge_base/7/Greet0001/x.pdf", False),
        ("noveum", "recordings/7/noveum/user/seg.wav", False),
        ("..", "recordings/7/../12.wav", False),
        ("a/b", "recordings/7/a/b/c.wav", False),
    ],
)
def test_prompt_recording_key_guard(recording_id, key, ok):
    from api.db.org_erasure_client import PromptRecordingObject
    from api.services.privacy.org_erasure import is_prompt_recording_key

    recording = PromptRecordingObject(
        id=1, recording_id=recording_id, storage_key=key, storage_backend="minio"
    )
    assert is_prompt_recording_key(7, recording) is ok


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        ("greeting.wav", "greeting.wav"),
        ("../../etc/passwd", "passwd"),
        ("dir\\take 1.wav", "take 1.wav"),
        ("héllo.mp3", "h_llo.mp3"),
        ("..", "recording"),
        (".hidden.wav", "hidden.wav"),
    ],
)
def test_recording_upload_filenames_are_one_safe_segment(given, stored):
    from api.schemas.workflow_recording import FileDescriptor

    assert FileDescriptor(filename=given, file_size=10).filename == stored
