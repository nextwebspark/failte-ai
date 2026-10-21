"""Callers' data requests: erasing one call, exporting and erasing a number's
calls, and deleting knowledge base documents and prompt audio for good."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from api.db import db_client
from api.db.models import (
    BillingLedgerEntryModel,
    CampaignModel,
    EmbedSessionModel,
    EmbedTokenModel,
    KnowledgeBaseChunkModel,
    KnowledgeBaseDocumentModel,
    OrganizationModel,
    QueuedRunModel,
    TelephonyConfigurationModel,
    TelephonyPhoneNumberModel,
    UserModel,
    WebhookDeliveryModel,
    WorkflowModel,
    WorkflowRecordingModel,
    WorkflowRunModel,
)
from api.db.retention_client import scrub_run_name
from api.enums import OrgRole
from api.routes import knowledge_base as knowledge_base_routes
from api.routes import organization_usage as usage_routes
from api.routes import workflow as workflow_routes
from api.routes import workflow_recording as recording_routes
from api.services.auth.depends import get_user
from api.services.privacy import call_erasure, stored_files
from api.services.privacy.call_erasure import (
    parse_subject_number,
    remove_subject_rows,
)
from api.services.privacy.stored_files import is_workflow_recording_key

NOW = datetime.now(UTC)
SUBJECT = "+353871234567"


# --- fakes and fixtures ------------------------------------------------------


class FakeStorage:
    """In-memory object store."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.failing: set[str] = set()

    def add(self, *keys: str, content: bytes = b"audio") -> None:
        for key in keys:
            self.objects[key] = content

    async def adelete_file(self, file_path: str) -> bool:
        if file_path in self.failing:
            return False
        self.objects.pop(file_path, None)
        return True

    async def adelete_prefix(self, prefix: str) -> int:
        keys = [key for key in self.objects if key.startswith(prefix)]
        for key in keys:
            del self.objects[key]
        return len(keys)

    async def aget_signed_url(self, file_path, expiration=3600, **_):
        assert expiration <= 3600
        return f"https://storage.test/{file_path}?expires={expiration}"

    async def adownload_file(self, source_path: str, local_path: str) -> bool:
        if source_path not in self.objects:
            return False
        with open(local_path, "wb") as handle:
            handle.write(self.objects[source_path])
        return True

    async def acreate_file_from_bytes(self, file_path: str, data: bytes) -> bool:
        if file_path in self.failing:
            return False
        self.objects[file_path] = data
        return True


@pytest.fixture
def storage(monkeypatch):
    fake = FakeStorage()
    resolver = lambda: lambda _backend: fake  # noqa: E731
    monkeypatch.setattr(call_erasure, "default_storage_resolver", resolver)
    monkeypatch.setattr(stored_files, "default_storage_resolver", resolver)
    return fake


async def make_org(session):
    org = OrganizationModel(provider_id=f"privacy-{uuid.uuid4().hex}")
    session.add(org)
    await session.flush()
    user = UserModel(
        provider_id=f"privacy-{uuid.uuid4().hex}", selected_organization_id=org.id
    )
    session.add(user)
    await session.flush()
    workflow = WorkflowModel(name="Reception", user_id=user.id, organization_id=org.id)
    session.add(workflow)
    await session.flush()
    return SimpleNamespace(org=org, user=user, workflow=workflow)


async def make_run(
    session,
    storage,
    workflow,
    *,
    context,
    completed=True,
    age=timedelta(days=2),
    call_type="inbound",
    name="WR-TEL-IN-00000001",
):
    run = WorkflowRunModel(
        name=name,
        workflow_id=workflow.id,
        mode="twilio",
        call_type=call_type,
        storage_backend="minio",
        created_at=NOW - age,
        initial_context=context,
        gathered_context={
            "call_disposition": "user_hangup",
            "mapped_call_disposition": "HUNGUP",
            "extracted_variables": {"name": "Aoife"},
        },
        logs={
            "realtime_feedback_events": [
                {
                    "type": "rtf-bot-text",
                    "timestamp": "2026-10-01T10:00:00+00:00",
                    "payload": {"text": "Hello, how can I help?"},
                },
                {
                    "type": "rtf-user-transcription",
                    "timestamp": "2026-10-01T10:00:02+00:00",
                    "payload": {"text": "This is Aoife", "final": True},
                },
            ]
        },
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
        "recordings": {
            "user": {
                "storage_key": f"recordings/{run.id}/user.wav",
                "storage_backend": "minio",
            }
        },
    }
    storage.add(
        f"recordings/{run.id}.wav",
        f"recordings/{run.id}/user.wav",
        f"recordings/{run.id}/noveum/user/seg-1.wav",
        f"transcripts/{run.id}.txt",
    )
    await session.flush()
    return run


def run_keys(run_id):
    return {
        f"recordings/{run_id}.wav",
        f"recordings/{run_id}/user.wav",
        f"recordings/{run_id}/noveum/user/seg-1.wav",
        f"transcripts/{run_id}.txt",
    }


def make_app(user, *routers):
    app = FastAPI()
    for router in routers:
        app.include_router(router)
    app.dependency_overrides[get_user] = lambda: user
    return app


async def client_for(user, *routers):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=make_app(user, *routers)),
        base_url="http://test",
    )


def assert_scrubbed(run):
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
    assert "purged_at" in run.extra
    # What billing and usage history need stays.
    assert run.usage_info == {"call_duration_seconds": 42}
    assert run.cost_info == {"total": 0.12}
    assert run.state == "completed"


# --- unit ----------------------------------------------------------------------


def test_numbers_are_normalized_before_matching():
    subject = parse_subject_number("+353 (87) 123-4567")
    assert subject.canonical == SUBJECT
    assert subject.prefilter.digits == "1234567"
    for stored in (
        "+353 87 123 4567",
        "+353871234567",
        "353871234567",
        "sip:+353871234567@pbx.example.com",
    ):
        assert call_erasure.context_names_subject({"caller_number": stored}, subject)
    assert not call_erasure.context_names_subject(
        {"caller_number": "+353871234568"}, subject
    )
    assert not call_erasure.context_names_subject({"note": SUBJECT}, subject)


@pytest.mark.parametrize("raw", ["", "  ", "12"])
def test_unusable_numbers_are_refused(raw):
    with pytest.raises(ValueError):
        parse_subject_number(raw)


def test_run_names_lose_the_number():
    context = {"caller_number": "+353 87 123 4567"}
    assert scrub_run_name("Inbound +353 87 123 4567", context) == "Inbound [removed]"
    assert scrub_run_name("ARI Inbound +353871234567", {}) == "ARI Inbound"
    assert scrub_run_name("WR-TEL-IN-00000001", context) == "WR-TEL-IN-00000001"


def test_csv_rows_of_the_subject_are_emptied_in_place():
    content = (
        b"\xef\xbb\xbfphone_number,first_name\r\n"
        b"+353 87 123 4567,Aoife\r\n"
        b"+353870000002,Cian\r\n"
    )
    rewritten, removed = remove_subject_rows(content, parse_subject_number(SUBJECT))
    assert removed == 1
    assert rewritten == (
        b"\xef\xbb\xbfphone_number,first_name\r\n,\r\n+353870000002,Cian\r\n"
    )
    unchanged, removed = remove_subject_rows(
        b"phone_number\n+353870000002\n", parse_subject_number(SUBJECT)
    )
    assert removed == 0 and unchanged == b"phone_number\n+353870000002\n"


def test_prompt_audio_keys_never_reach_call_recordings():
    assert is_workflow_recording_key(12, "recordings/12/AbCd1234/greeting.wav")
    assert not is_workflow_recording_key(12, "recordings/12/user.wav")
    assert not is_workflow_recording_key(12, "recordings/12/noveum/user/a.wav")
    assert not is_workflow_recording_key(12, "recordings/13/AbCd1234/greeting.wav")
    assert not is_workflow_recording_key(12, "recordings/12.wav")


# --- delete one call -----------------------------------------------------------


async def test_deleting_a_call_erases_its_content_and_keeps_billing(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    run = await make_run(
        async_session,
        storage,
        data.workflow,
        context={"caller_number": SUBJECT, "called_number": "+35315550000"},
        name=f"Inbound {SUBJECT}",
    )
    # Prompt audio of this organization and of an organization whose id
    # equals the run id: neither is the call's.
    prompt_audio = {
        f"recordings/{data.org.id}/AbCd1234/greeting.wav",
        f"recordings/{run.id}/AbCd1234/greeting.wav",
    }
    storage.add(*prompt_audio)
    ledger = BillingLedgerEntryModel(
        organization_id=data.org.id,
        entry_type="usage",
        amount_eur=Decimal("-0.12"),
        balance_after_eur=Decimal("9.88"),
        workflow_run_id=run.id,
    )
    token = EmbedTokenModel(
        token=f"emb-{uuid.uuid4().hex}",
        workflow_id=data.workflow.id,
        organization_id=data.org.id,
        created_by=data.user.id,
    )
    async_session.add_all([ledger, token])
    await async_session.flush()
    embed_session = EmbedSessionModel(
        session_token=uuid.uuid4().hex,
        embed_token_id=token.id,
        workflow_run_id=run.id,
        client_ip="203.0.113.7",
        user_agent="Mozilla/5.0",
        expires_at=NOW + timedelta(hours=1),
    )
    deliveries = [
        WebhookDeliveryModel(
            workflow_run_id=run.id,
            organization_id=data.org.id,
            endpoint_url="https://crm.example.com/hook",
            payload={"caller": SUBJECT},
            webhook_node_id=node,
            status=status,
            last_error="timeout" if status == "pending" else None,
        )
        for node, status in (("n1", "succeeded"), ("n2", "pending"))
    ]
    async_session.add_all([embed_session, *deliveries])
    await async_session.commit()

    async with await client_for(data.user, workflow_routes.router) as client:
        response = await client.delete(f"/workflow/{data.workflow.id}/runs/{run.id}")

    assert response.status_code == 200, response.text
    assert response.json() == {"run_id": run.id, "objects_deleted": 5}
    assert storage.objects.keys().isdisjoint(run_keys(run.id))
    assert prompt_audio <= storage.objects.keys()

    await async_session.refresh(run)
    assert_scrubbed(run)
    assert run.name == "Inbound [removed]"
    await async_session.refresh(ledger)
    assert ledger.workflow_run_id == run.id
    await async_session.refresh(embed_session)
    assert embed_session.client_ip is None and embed_session.user_agent is None
    for delivery in deliveries:
        await async_session.refresh(delivery)
        assert delivery.payload == {} and delivery.last_error is None
    assert [d.status for d in deliveries] == ["succeeded", "dead_letter"]

    # Repeating the request is harmless.
    async with await client_for(data.user, workflow_routes.router) as client:
        again = await client.delete(f"/workflow/{data.workflow.id}/runs/{run.id}")
    assert again.status_code == 200


async def test_deleting_another_organizations_call_is_not_found(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    other = await make_org(async_session)
    run = await make_run(
        async_session, storage, other.workflow, context={"caller_number": SUBJECT}
    )
    await async_session.commit()

    async with await client_for(data.user, workflow_routes.router) as client:
        foreign = await client.delete(f"/workflow/{other.workflow.id}/runs/{run.id}")
        wrong_workflow = await client.delete(
            f"/workflow/{data.workflow.id}/runs/{run.id}"
        )

    assert foreign.status_code == 404
    assert wrong_workflow.status_code == 404
    assert run_keys(run.id) <= storage.objects.keys()
    await async_session.refresh(run)
    assert run.initial_context == {"caller_number": SUBJECT}


async def test_a_call_in_progress_cannot_be_deleted(db_session, async_session, storage):
    data = await make_org(async_session)
    run = await make_run(
        async_session,
        storage,
        data.workflow,
        context={"caller_number": SUBJECT},
        completed=False,
        age=timedelta(minutes=3),
    )
    await async_session.commit()

    async with await client_for(data.user, workflow_routes.router) as client:
        response = await client.delete(f"/workflow/{data.workflow.id}/runs/{run.id}")

    assert response.status_code == 409
    assert run_keys(run.id) <= storage.objects.keys()


async def test_an_abandoned_unfinished_call_can_be_deleted(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    run = await make_run(
        async_session,
        storage,
        data.workflow,
        context={"caller_number": SUBJECT},
        completed=False,
        age=timedelta(days=1),
    )
    await async_session.commit()

    async with await client_for(data.user, workflow_routes.router) as client:
        response = await client.delete(f"/workflow/{data.workflow.id}/runs/{run.id}")

    assert response.status_code == 200
    await async_session.refresh(run)
    assert run.initial_context == {}


async def test_nothing_is_scrubbed_when_storage_fails(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    run = await make_run(
        async_session, storage, data.workflow, context={"caller_number": SUBJECT}
    )
    storage.failing.add(f"recordings/{run.id}.wav")
    await async_session.commit()

    async with await client_for(data.user, workflow_routes.router) as client:
        response = await client.delete(f"/workflow/{data.workflow.id}/runs/{run.id}")

    assert response.status_code == 502
    await async_session.refresh(run)
    assert run.initial_context == {"caller_number": SUBJECT}
    assert run.recording_url == f"recordings/{run.id}.wav"


# --- a caller's request ----------------------------------------------------------


async def make_number_fixture(async_session, storage):
    """One organization with calls to and from the subject in every form."""
    data = await make_org(async_session)
    other = await make_org(async_session)
    inbound = await make_run(
        async_session,
        storage,
        data.workflow,
        context={"caller_number": "+353 87 123 4567", "called_number": "+35315550000"},
    )
    outbound = await make_run(
        async_session,
        storage,
        data.workflow,
        context={"caller_number": "+35315550000", "called_number": "353871234567"},
        call_type="outbound",
    )
    campaign_call = await make_run(
        async_session,
        storage,
        data.workflow,
        context={"phone_number": "sip:+353871234567@pbx.example.com"},
        call_type="outbound",
    )
    someone_else = await make_run(
        async_session,
        storage,
        data.workflow,
        context={"caller_number": "+353871234568", "called_number": "+35315550000"},
    )
    other_org = await make_run(
        async_session, storage, other.workflow, context={"caller_number": SUBJECT}
    )
    in_progress = await make_run(
        async_session,
        storage,
        data.workflow,
        context={"caller_number": SUBJECT},
        completed=False,
        age=timedelta(minutes=1),
    )

    csv_key = f"campaigns/{data.org.id}/{uuid.uuid4()}_list.csv"
    storage.add(
        csv_key,
        content=b"phone_number,first_name\n+353 87 123 4567,Aoife\n+353870000002,Cian\n",
    )
    other_csv_key = f"campaigns/{other.org.id}/{uuid.uuid4()}_list.csv"
    storage.add(other_csv_key, content=b"phone_number\n+353871234567\n")
    campaign = CampaignModel(
        name="Autumn calls",
        organization_id=data.org.id,
        workflow_id=data.workflow.id,
        created_by=data.user.id,
        source_type="csv",
        source_id=csv_key,
        state="running",
    )
    other_campaign = CampaignModel(
        name="Their calls",
        organization_id=other.org.id,
        workflow_id=other.workflow.id,
        created_by=other.user.id,
        source_type="csv",
        source_id=other_csv_key,
        state="running",
    )
    async_session.add_all([campaign, other_campaign])
    await async_session.flush()
    pending = QueuedRunModel(
        campaign_id=campaign.id,
        source_uuid="csv_x_row_1",
        context_variables={"phone_number": "+353 87 123 4567", "first_name": "Aoife"},
        state="queued",
    )
    dialled = QueuedRunModel(
        campaign_id=campaign.id,
        source_uuid="csv_y_row_1",
        context_variables={"phone_number": SUBJECT, "first_name": "Aoife"},
        state="processed",
    )
    neighbour = QueuedRunModel(
        campaign_id=campaign.id,
        source_uuid="csv_x_row_2",
        context_variables={"phone_number": "+353870000002", "first_name": "Cian"},
        state="queued",
    )
    other_pending = QueuedRunModel(
        campaign_id=other_campaign.id,
        source_uuid="csv_z_row_1",
        context_variables={"phone_number": SUBJECT},
        state="queued",
    )
    async_session.add_all([pending, dialled, neighbour, other_pending])
    await async_session.flush()
    campaign_call.queued_run_id = dialled.id
    await async_session.commit()
    return SimpleNamespace(
        data=data,
        other=other,
        inbound=inbound,
        outbound=outbound,
        campaign_call=campaign_call,
        someone_else=someone_else,
        other_org=other_org,
        in_progress=in_progress,
        csv_key=csv_key,
        other_csv_key=other_csv_key,
        campaign=campaign,
        pending=pending,
        dialled=dialled,
        neighbour=neighbour,
        other_pending=other_pending,
    )


async def test_caller_data_export_finds_every_call_of_the_number(
    db_session, async_session, storage
):
    f = await make_number_fixture(async_session, storage)

    async with await client_for(f.data.user, usage_routes.router) as client:
        response = await client.get(
            "/organizations/usage/subject-data",
            params={"number": "+353 (87) 123-4567"},
        )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["number"] == SUBJECT
    assert body["truncated"] is False
    calls = {call["id"]: call for call in body["calls"]}
    assert set(calls) == {
        f.inbound.id,
        f.outbound.id,
        f.campaign_call.id,
        f.in_progress.id,
    }
    inbound = calls[f.inbound.id]
    assert inbound["workflow_name"] == "Reception"
    assert inbound["direction"] == "inbound"
    assert calls[f.outbound.id]["direction"] == "outbound"
    assert inbound["duration_seconds"] == 42
    assert inbound["disposition"] == "HUNGUP"
    assert inbound["in_progress"] is False
    assert calls[f.in_progress.id]["in_progress"] is True
    assert inbound["initial_context"]["caller_number"] == "+353 87 123 4567"
    assert inbound["gathered_context"]["extracted_variables"] == {"name": "Aoife"}
    assert [line["text"] for line in inbound["transcript"]] == [
        "Hello, how can I help?",
        "This is Aoife",
    ]
    assert inbound["files"]["recording"] == (
        f"https://storage.test/recordings/{f.inbound.id}.wav?expires=3600"
    )
    assert inbound["files"]["user_recording"].startswith(
        f"https://storage.test/recordings/{f.inbound.id}/user.wav"
    )
    assert inbound["files"]["bot_recording"] is None
    assert inbound["files"]["transcript"].startswith(
        f"https://storage.test/transcripts/{f.inbound.id}.txt"
    )
    queued = {row["id"]: row for row in body["queued_calls"]}
    assert set(queued) == {f.pending.id, f.dialled.id}
    assert queued[f.pending.id]["campaign_name"] == "Autumn calls"


async def test_caller_data_erase_removes_every_trace_of_the_number(
    db_session, async_session, storage
):
    f = await make_number_fixture(async_session, storage)
    prompt_audio = f"recordings/{f.data.org.id}/AbCd1234/greeting.wav"
    storage.add(prompt_audio)

    async with await client_for(f.data.user, usage_routes.router) as client:
        response = await client.post(
            "/organizations/usage/subject-data/erase",
            json={"number": "+353 87 123 4567"},
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "number": SUBJECT,
        "calls_erased": 3,
        "calls_in_progress": [f.in_progress.id],
        "calls_failed": [],
        "objects_deleted": 15,
        "queued_calls_deleted": 1,
        "queued_calls_cleared": 1,
        "queued_calls_in_progress": 0,
        "campaign_lists_rewritten": 1,
        "campaign_list_rows_removed": 1,
        "campaign_lists_failed": [],
    }

    for run in (f.inbound, f.outbound, f.campaign_call):
        await async_session.refresh(run)
        assert_scrubbed(run)
        assert storage.objects.keys().isdisjoint(run_keys(run.id))
    for untouched in (f.someone_else, f.other_org, f.in_progress):
        await async_session.refresh(untouched)
        assert untouched.initial_context != {}
        assert run_keys(untouched.id) <= storage.objects.keys()
    assert prompt_audio in storage.objects

    remaining = {
        row.id: row
        for row in (
            await async_session.execute(
                select(QueuedRunModel).where(
                    QueuedRunModel.id.in_(
                        [
                            f.pending.id,
                            f.dialled.id,
                            f.neighbour.id,
                            f.other_pending.id,
                        ]
                    )
                )
            )
        ).scalars()
    }
    assert f.pending.id not in remaining
    for row in remaining.values():
        await async_session.refresh(row)
    assert remaining[f.dialled.id].context_variables == {}
    assert remaining[f.dialled.id].state == "processed"
    assert remaining[f.neighbour.id].context_variables["first_name"] == "Cian"
    assert remaining[f.other_pending.id].context_variables == {"phone_number": SUBJECT}

    assert storage.objects[f.csv_key] == (
        b"phone_number,first_name\n,\n+353870000002,Cian\n"
    )
    assert storage.objects[f.other_csv_key] == b"phone_number\n+353871234567\n"


async def test_an_organizations_own_number_is_refused(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    config = TelephonyConfigurationModel(
        organization_id=data.org.id, name="Main", provider="twilio", credentials={}
    )
    async_session.add(config)
    await async_session.flush()
    async_session.add(
        TelephonyPhoneNumberModel(
            organization_id=data.org.id,
            telephony_configuration_id=config.id,
            address="+353 1 555 0000",
            address_normalized="+35315550000",
            address_type="pstn",
        )
    )
    run = await make_run(
        async_session,
        storage,
        data.workflow,
        context={"caller_number": SUBJECT, "called_number": "+35315550000"},
    )
    await async_session.commit()

    async with await client_for(data.user, usage_routes.router) as client:
        export = await client.get(
            "/organizations/usage/subject-data", params={"number": "+353 1 555 0000"}
        )
        erase = await client.post(
            "/organizations/usage/subject-data/erase", json={"number": "+35315550000"}
        )

    assert export.status_code == 400
    assert erase.status_code == 400
    assert "own numbers" in erase.json()["detail"]
    await async_session.refresh(run)
    assert run.initial_context["caller_number"] == SUBJECT


# --- roles -------------------------------------------------------------------------


@pytest.mark.real_org_roles
@pytest.mark.parametrize("role", [OrgRole.VIEWER, OrgRole.DEVELOPER])
async def test_only_admins_can_answer_caller_requests(monkeypatch, role):
    monkeypatch.setattr(db_client, "get_member_role", AsyncMock(return_value=role))
    erase = AsyncMock()
    monkeypatch.setattr(workflow_routes, "erase_workflow_run", erase)
    monkeypatch.setattr(usage_routes, "erase_subject_data", erase)
    monkeypatch.setattr(usage_routes, "export_subject_data", erase)
    user = SimpleNamespace(id=1, selected_organization_id=1, is_superuser=False)

    async with await client_for(
        user, workflow_routes.router, usage_routes.router
    ) as client:
        responses = [
            await client.delete("/workflow/1/runs/2"),
            await client.get(
                "/organizations/usage/subject-data", params={"number": SUBJECT}
            ),
            await client.post(
                "/organizations/usage/subject-data/erase", json={"number": SUBJECT}
            ),
        ]

    assert [r.status_code for r in responses] == [403, 403, 403]
    erase.assert_not_awaited()


# --- uploaded files ----------------------------------------------------------------


async def test_deleting_a_document_removes_its_chunks_and_file(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    document_uuid = str(uuid.uuid4())
    key = f"knowledge_base/{data.org.id}/{document_uuid}/handbook.pdf"
    storage.add(key, f"knowledge_base/{data.org.id}/{document_uuid}/derived.md")
    neighbour = f"knowledge_base/{data.org.id}/{uuid.uuid4()}/other.pdf"
    storage.add(neighbour)
    document = KnowledgeBaseDocumentModel(
        document_uuid=document_uuid,
        organization_id=data.org.id,
        filename="handbook.pdf",
        custom_metadata={"s3_key": key},
        created_by=data.user.id,
        is_active=False,  # soft-deleted before deletes were permanent
    )
    async_session.add(document)
    await async_session.flush()
    async_session.add(
        KnowledgeBaseChunkModel(
            document_id=document.id,
            organization_id=data.org.id,
            chunk_text="Opening hours",
            chunk_index=0,
            embedding_model="test",
            embedding_dimension=1536,
        )
    )
    await async_session.commit()
    document_id = document.id

    async with await client_for(data.user, knowledge_base_routes.router) as client:
        response = await client.delete(f"/knowledge-base/documents/{document_uuid}")

    assert response.status_code == 200, response.text
    assert set(storage.objects) == {neighbour}
    async_session.expunge_all()
    assert await async_session.get(KnowledgeBaseDocumentModel, document_id) is None
    chunks = await async_session.execute(
        select(KnowledgeBaseChunkModel).where(
            KnowledgeBaseChunkModel.document_id == document_id
        )
    )
    assert chunks.first() is None


async def test_document_row_stays_when_its_file_cannot_be_deleted(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    other = await make_org(async_session)
    document_uuid = str(uuid.uuid4())
    key = f"knowledge_base/{data.org.id}/{document_uuid}/handbook.pdf"
    storage.add(key)
    storage.failing.add(key)
    async_session.add(
        KnowledgeBaseDocumentModel(
            document_uuid=document_uuid,
            organization_id=data.org.id,
            filename="handbook.pdf",
            custom_metadata={"s3_key": key},
            created_by=data.user.id,
        )
    )
    await async_session.commit()

    async with await client_for(other.user, knowledge_base_routes.router) as client:
        foreign = await client.delete(f"/knowledge-base/documents/{document_uuid}")
    async with await client_for(data.user, knowledge_base_routes.router) as client:
        failed = await client.delete(f"/knowledge-base/documents/{document_uuid}")

    assert foreign.status_code == 404
    assert failed.status_code == 502
    assert key in storage.objects
    assert await db_client.get_document_for_deletion(document_uuid, data.org.id)


async def test_deleting_a_recording_removes_its_audio(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    key = f"recordings/{data.org.id}/AbCd1234/greeting.wav"
    other_audio = f"recordings/{data.org.id}/EfGh5678/goodbye.wav"
    storage.add(key, other_audio)
    recording = WorkflowRecordingModel(
        recording_id="AbCd1234",
        organization_id=data.org.id,
        transcript="Hello",
        storage_key=key,
        storage_backend="minio",
        created_by=data.user.id,
    )
    async_session.add(recording)
    await async_session.commit()
    recording_pk = recording.id

    async with await client_for(data.user, recording_routes.router) as client:
        response = await client.delete("/workflow-recordings/AbCd1234")

    assert response.status_code == 200, response.text
    assert set(storage.objects) == {other_audio}
    async_session.expunge_all()
    assert await async_session.get(WorkflowRecordingModel, recording_pk) is None


async def test_a_recording_never_deletes_a_file_outside_its_folder(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    call_audio = f"recordings/{data.org.id}/user.wav"
    storage.add(call_audio)
    async_session.add(
        WorkflowRecordingModel(
            recording_id="IjKl9012",
            organization_id=data.org.id,
            transcript="Hello",
            storage_key=call_audio,
            storage_backend="minio",
            created_by=data.user.id,
        )
    )
    await async_session.commit()

    async with await client_for(data.user, recording_routes.router) as client:
        response = await client.delete("/workflow-recordings/IjKl9012")
        create = await client.post(
            "/workflow-recordings/",
            json={
                "recordings": [
                    {
                        "recording_id": "MnOp3456",
                        "transcript": "Hi",
                        "storage_key": call_audio,
                    }
                ]
            },
        )

    assert response.status_code == 200
    assert call_audio in storage.objects
    assert create.status_code == 400
