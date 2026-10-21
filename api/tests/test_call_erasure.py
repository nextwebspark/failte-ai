"""Callers' data requests: erasing one call, exporting and erasing a number's
calls, and deleting knowledge base documents and prompt audio for good."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
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
from api.services.privacy.call_erasure import remove_subject_rows
from api.services.privacy.phone_matching import parse_subject_number
from api.services.privacy.stored_files import (
    is_safe_storage_key,
    is_workflow_recording_key,
)

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
        "00353 87 123 4567",
        "+00353871234567",
        "0871234567",  # national, in the subject's own country
        "+0871234567",
        "sip:+353871234567@pbx.example.com",
        "sip:0871234567@pbx.example.com",
    ):
        assert subject.matches(stored), stored
    for stored in ("+353871234568", "+44871234567", "", None, "anonymous"):
        assert not subject.matches(stored), stored


def test_national_numbers_are_read_in_the_organizations_countries():
    irish_org = frozenset({"353"})
    uk_caller = parse_subject_number("+44 871 234 567", irish_org)
    # An Irish org's national "0871234567" is Irish, not this UK caller.
    assert not uk_caller.matches("0871234567")
    assert uk_caller.matches("0044871234567")

    # Exotel sends Indian numbers in national format.
    indian_org = frozenset({"91"})
    caller = parse_subject_number("+91 94412 33609", indian_org)
    assert caller.matches("09441233609")
    assert caller.matches("+919441233609")
    assert not caller.matches("09441233608")

    # National input needs to know the country.
    assert parse_subject_number("094412 33609", indian_org).canonical == (
        "+919441233609"
    )
    with pytest.raises(ValueError, match="international format"):
        parse_subject_number("0871234567", frozenset())
    with pytest.raises(ValueError, match="international format"):
        parse_subject_number("0871234567", frozenset({"353", "44"}))


def test_a_sip_uri_and_a_plain_number_match_both_ways():
    subject = parse_subject_number("sip:+353871234567@pbx.example.com")
    assert subject.matches("+353 87 123 4567")
    assert subject.matches("sip:+353871234567@pbx.example.com")
    assert parse_subject_number("+353871234567").matches(
        "sips:+353871234567@other.example.com;transport=tls"
    )


def test_only_the_other_party_of_a_call_is_compared():
    subject = parse_subject_number(SUBJECT)
    inbound = {"caller_number": SUBJECT, "called_number": "+35315550000"}
    outbound = {"caller_number": "+35315550000", "called_number": SUBJECT}
    assert call_erasure.run_names_subject("inbound", inbound, subject)
    assert call_erasure.run_names_subject("outbound", outbound, subject)
    assert call_erasure.run_names_subject(
        "outbound", {"phone_number": SUBJECT}, subject
    )
    # The subject on the organization's side: their own line, not them.
    assert not call_erasure.run_names_subject("inbound", outbound, subject)
    assert not call_erasure.run_names_subject("outbound", inbound, subject)


def test_storage_keys_must_be_plain_relative_paths():
    assert is_safe_storage_key("knowledge_base/1/u/a.pdf")
    for key in (
        "knowledge_base/1/u/../../2/x.pdf",
        "knowledge_base/1/u/..",
        "knowledge_base\\1\\u\\a.pdf",
        "/knowledge_base/1/u/a.pdf",
        "knowledge_base//1/a.pdf",
        "knowledge_base/1/u/a\n.pdf",
        "",
        None,
    ):
        assert not is_safe_storage_key(key), key
    assert not is_workflow_recording_key(12, "recordings/12/AbCd1234/../../13/x.wav")


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
        response = await client.post(
            "/organizations/usage/subject-data/export",
            json={"number": "+353 (87) 123-4567"},
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
        export = await client.post(
            "/organizations/usage/subject-data/export",
            json={"number": "+353 1 555 0000"},
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
            await client.post(
                "/organizations/usage/subject-data/export", json={"number": SUBJECT}
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


# --- late writes after hangup ------------------------------------------------------


async def test_a_call_is_in_progress_until_post_call_processing_is_done(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    run = await make_run(
        async_session,
        storage,
        data.workflow,
        context={"caller_number": SUBJECT},
        age=timedelta(minutes=5),
    )
    await async_session.commit()
    url = f"/workflow/{data.workflow.id}/runs/{run.id}"

    async with await client_for(data.user, workflow_routes.router) as client:
        # Hung up, but QA, webhooks and uploads may still be writing.
        assert (await client.delete(url)).status_code == 409

        just_now = datetime.now(UTC)
        run.extra = {**run.extra, "post_call_done_at": just_now.isoformat()}
        await async_session.commit()
        # Done just now: the last in-flight write may still land.
        assert (await client.delete(url)).status_code == 409

        run.extra = {
            **run.extra,
            "post_call_done_at": (just_now - timedelta(minutes=3)).isoformat(),
        }
        await async_session.commit()
        assert (await client.delete(url)).status_code == 200

    await async_session.refresh(run)
    assert_scrubbed(run)
    assert "post_call_done_at" in run.extra


async def test_erasing_again_removes_what_was_written_after_the_first_erase(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    run = await make_run(
        async_session, storage, data.workflow, context={"caller_number": SUBJECT}
    )
    await async_session.commit()
    url = f"/workflow/{data.workflow.id}/runs/{run.id}"

    async with await client_for(data.user, workflow_routes.router) as client:
        assert (await client.delete(url)).status_code == 200
        # A late writer stores a transcript, a recording and QA results.
        await db_client.update_workflow_run(
            run_id=run.id,
            logs={"realtime_feedback_events": [{"text": "late"}]},
            annotations={"qa": "late"},
            recording_url=f"recordings/{run.id}.wav",
        )
        storage.add(f"recordings/{run.id}.wav")
        assert (await client.delete(url)).status_code == 200

    await async_session.refresh(run)
    assert run.logs == {}
    assert run.annotations == {}
    assert run.recording_url is None
    assert f"recordings/{run.id}.wav" not in storage.objects


async def test_post_call_jobs_mark_the_run_done(monkeypatch):
    from api.tasks import run_integrations, workflow_completion

    marked = AsyncMock()
    inner = AsyncMock(side_effect=RuntimeError("integration failed"))
    monkeypatch.setattr(run_integrations, "mark_post_call_done", marked)
    monkeypatch.setattr(run_integrations, "_run_integrations_post_workflow_run", inner)

    # Run on its own (a call that never connected): marks even on failure.
    with pytest.raises(RuntimeError):
        await run_integrations.run_integrations_post_workflow_run(None, 5)
    marked.assert_awaited_once_with(5)

    # Inside the completion job, only the job marks, once it is all done.
    marked.reset_mock()
    integrations = AsyncMock()
    monkeypatch.setattr(
        workflow_completion, "run_integrations_post_workflow_run", integrations
    )
    monkeypatch.setattr(workflow_completion, "mark_post_call_done", marked)
    monkeypatch.setattr(
        workflow_completion, "report_completed_workflow_run_platform_usage", AsyncMock()
    )
    monkeypatch.setattr(
        workflow_completion, "sync_external_pbx_call_record", AsyncMock()
    )
    await workflow_completion.process_workflow_completion(None, 6)
    integrations.assert_awaited_once_with(None, 6, mark_done=False)
    marked.assert_awaited_once_with(6)


async def test_mark_post_call_done_stamps_the_run(db_session, async_session, storage):
    from api.tasks.run_integrations import mark_post_call_done

    data = await make_org(async_session)
    run = await make_run(async_session, storage, data.workflow, context={})
    await async_session.commit()

    await mark_post_call_done(run.id)

    await async_session.refresh(run)
    assert run.extra["use_draft"] is False
    assert datetime.fromisoformat(run.extra["post_call_done_at"]) <= datetime.now(UTC)


# --- number formats and sides ------------------------------------------------------


async def add_own_number(session, org, address, country):
    config = TelephonyConfigurationModel(
        organization_id=org.id,
        name=f"Line {uuid.uuid4().hex[:6]}",
        provider="twilio",
        credentials={},
    )
    session.add(config)
    await session.flush()
    session.add(
        TelephonyPhoneNumberModel(
            organization_id=org.id,
            telephony_configuration_id=config.id,
            address=address,
            address_normalized=address,
            address_type="pstn",
            country_code=country,
        )
    )
    await session.flush()


async def test_national_and_00_format_numbers_are_found(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    await add_own_number(async_session, data.org, "+918037091588", "IN")
    subject_runs = [
        await make_run(
            async_session,
            storage,
            data.workflow,
            context={"caller_number": stored, "called_number": "08037091588"},
        )
        for stored in ("09441233609", "0091 94412 33609", "+09441233609")
    ]
    other = await make_run(
        async_session,
        storage,
        data.workflow,
        context={"caller_number": "09441233608", "called_number": "08037091588"},
    )
    await async_session.commit()

    async with await client_for(data.user, usage_routes.router) as client:
        export = await client.post(
            "/organizations/usage/subject-data/export",
            json={"number": "+91 94412 33609"},
        )
        national = await client.post(
            "/organizations/usage/subject-data/export", json={"number": "09441233609"}
        )
        own_national = await client.post(
            "/organizations/usage/subject-data/erase", json={"number": "080 3709 1588"}
        )

    assert export.status_code == 200, export.text
    assert {call["id"] for call in export.json()["calls"]} == {
        run.id for run in subject_runs
    }
    assert national.json()["number"] == "+919441233609"
    assert {call["id"] for call in national.json()["calls"]} == {
        run.id for run in subject_runs
    }
    assert own_national.status_code == 400
    await async_session.refresh(other)
    assert other.initial_context["caller_number"] == "09441233608"


async def test_the_organizations_side_of_a_call_never_matches(
    db_session, async_session, storage
):
    """A number the organization dialled out from (or that was called) is its
    own line on that call, even once the number is released from the account."""
    data = await make_org(async_session)
    released = "+35315559999"
    outbound_from_it = await make_run(
        async_session,
        storage,
        data.workflow,
        context={"caller_number": released, "called_number": "+353870000009"},
        call_type="outbound",
    )
    inbound_to_it = await make_run(
        async_session,
        storage,
        data.workflow,
        context={"caller_number": "+353870000009", "called_number": released},
    )
    await async_session.commit()

    async with await client_for(data.user, usage_routes.router) as client:
        response = await client.post(
            "/organizations/usage/subject-data/erase", json={"number": released}
        )

    assert response.status_code == 200
    assert response.json()["calls_erased"] == 0
    for run in (outbound_from_it, inbound_to_it):
        await async_session.refresh(run)
        assert run.initial_context != {}


async def test_upload_keys_with_dot_segments_are_refused(
    db_session, async_session, storage, monkeypatch
):
    data = await make_org(async_session)
    await async_session.commit()
    org_id = data.org.id

    async with await client_for(data.user, recording_routes.router) as client:
        response = await client.post(
            "/workflow-recordings/",
            json={
                "recordings": [
                    {
                        "recording_id": "MnOp3456",
                        "transcript": "Hi",
                        "storage_key": (
                            f"recordings/{org_id}/MnOp3456/../../{org_id + 1}/a.wav"
                        ),
                    }
                ]
            },
        )
    assert response.status_code == 400

    monkeypatch.setattr(
        knowledge_base_routes, "_require_document_processing", lambda: None
    )
    document_uuid = str(uuid.uuid4())
    with pytest.raises(HTTPException) as exc:
        await knowledge_base_routes.process_document(
            knowledge_base_routes.ProcessDocumentRequestSchema(
                document_uuid=document_uuid,
                s3_key=f"knowledge_base/{org_id}/{document_uuid}/../../9/x.pdf",
                retrieval_mode="full_document",
            ),
            user=data.user,
        )
    assert exc.value.status_code == 400


# --- archived uploads -----------------------------------------------------------------


async def test_retention_purge_deletes_archived_documents_and_recordings(
    db_session, async_session, storage
):
    from api.services.retention import purge_expired_data

    data = await make_org(async_session)
    archived_uuid, active_uuid = str(uuid.uuid4()), str(uuid.uuid4())
    archived_key = f"knowledge_base/{data.org.id}/{archived_uuid}/old.pdf"
    active_key = f"knowledge_base/{data.org.id}/{active_uuid}/new.pdf"
    old_audio = f"recordings/{data.org.id}/Arch1234/old.wav"
    live_audio = f"recordings/{data.org.id}/Live1234/new.wav"
    storage.add(archived_key, active_key, old_audio, live_audio)
    async_session.add_all(
        [
            KnowledgeBaseDocumentModel(
                document_uuid=uuid_,
                organization_id=data.org.id,
                filename="doc.pdf",
                custom_metadata={"s3_key": key},
                created_by=data.user.id,
                is_active=active,
            )
            for uuid_, key, active in (
                (archived_uuid, archived_key, False),
                (active_uuid, active_key, True),
            )
        ]
        + [
            WorkflowRecordingModel(
                recording_id=rid,
                organization_id=data.org.id,
                transcript="Hello",
                storage_key=key,
                storage_backend="minio",
                created_by=data.user.id,
                is_active=active,
            )
            for rid, key, active in (
                ("Arch1234", old_audio, False),
                ("Live1234", live_audio, True),
            )
        ]
    )
    await async_session.commit()

    result = await purge_expired_data(resolve_storage=lambda _backend: storage)

    assert result.archived_documents_deleted >= 1
    assert result.archived_recordings_deleted >= 1
    assert archived_key not in storage.objects and old_audio not in storage.objects
    assert active_key in storage.objects and live_audio in storage.objects
    assert await db_client.get_document_for_deletion(archived_uuid, data.org.id) is None
    assert await db_client.get_document_for_deletion(active_uuid, data.org.id)
    assert (
        await db_client.get_recording_for_deletion(data.org.id, recording_id="Arch1234")
        is None
    )
    assert await db_client.get_recording_for_deletion(
        data.org.id, recording_id="Live1234"
    )


# --- second review: late writers, bare numbers, archived recordings --------------------


async def erase_one(data, run):
    async with await client_for(data.user, workflow_routes.router) as client:
        response = await client.delete(f"/workflow/{data.workflow.id}/runs/{run.id}")
    assert response.status_code == 200, response.text


async def test_writes_after_erasure_cannot_bring_content_back(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    run = await make_run(
        async_session, storage, data.workflow, context={"caller_number": SUBJECT}
    )
    await async_session.commit()
    await erase_one(data, run)

    # The final variable extraction, QA and an artifact upload land late.
    await db_client.update_workflow_run(
        run_id=run.id,
        initial_context={"caller_number": SUBJECT},
        gathered_context={
            "extracted_variables": {"name": "Aoife"},
            "call_disposition": "transferred",
        },
        annotations={"qa": "Aoife was polite"},
        recording_url=f"recordings/{run.id}.wav",
        transcript_url=f"transcripts/{run.id}.txt",
        logs={"realtime_feedback_events": [{"text": "late"}]},
        extra={"recordings": {"mixed": f"recordings/{run.id}.wav"}},
        usage_info={"call_duration_seconds": 50},
    )

    async_session.expire_all()
    await async_session.refresh(run)
    assert run.initial_context == {}
    assert run.annotations == {}
    assert run.logs == {}
    assert run.recording_url is None and run.transcript_url is None
    assert "recordings" not in run.extra and "purged_at" in run.extra
    # Outcome labels and usage may still be updated.
    assert run.gathered_context == {
        "call_disposition": "transferred",
        "mapped_call_disposition": "HUNGUP",
    }
    assert run.usage_info == {"call_duration_seconds": 50}


async def test_a_late_status_callback_does_not_store_the_callers_number(
    db_session, async_session, storage
):
    from api.services.telephony.status_processor import (
        StatusCallbackRequest,
        _process_status_update,
    )

    data = await make_org(async_session)
    run = await make_run(
        async_session, storage, data.workflow, context={"caller_number": SUBJECT}
    )
    await async_session.commit()
    await erase_one(data, run)

    await _process_status_update(
        run.id,
        StatusCallbackRequest(
            call_id="CA123",
            status="ringing",
            from_number=SUBJECT,
            extra={"From": SUBJECT, "Caller": SUBJECT},
        ),
    )

    async_session.expire_all()
    await async_session.refresh(run)
    assert run.logs == {}
    assert SUBJECT not in str(run.initial_context) + str(run.gathered_context)


async def test_webhooks_for_an_erased_call_are_never_sent(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    run = await make_run(
        async_session, storage, data.workflow, context={"caller_number": SUBJECT}
    )
    await async_session.commit()
    await erase_one(data, run)

    delivery, created = await db_client.create_webhook_delivery(
        workflow_run_id=run.id,
        organization_id=data.org.id,
        endpoint_url="https://crm.example.com/hook",
        payload={"caller": SUBJECT},
        max_attempts=5,
        webhook_node_id="late",
    )

    assert created is False
    assert delivery.payload == {}
    assert delivery.status == "dead_letter"


async def test_a_failed_send_does_not_revive_an_erased_delivery(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    run = await make_run(async_session, storage, data.workflow, context={})
    delivery = WebhookDeliveryModel(
        workflow_run_id=run.id,
        organization_id=data.org.id,
        endpoint_url="https://crm.example.com/hook",
        payload={},
        webhook_node_id="n1",
        status="dead_letter",
    )
    async_session.add(delivery)
    await async_session.commit()

    await db_client.schedule_webhook_delivery_retry(
        delivery.id,
        attempt_count=2,
        scheduled_for=NOW,
        last_error="timeout",
        last_status_code=None,
    )

    await async_session.refresh(delivery)
    assert delivery.status == "dead_letter"


@pytest.mark.parametrize(
    "typed",
    [
        "(202) 555-0143",  # US national, would read as +20 (Egypt)
        "912 345 678",  # Spanish national, would read as +91 (India)
        "2025550143",
    ],
)
def test_bare_digits_are_refused_as_input(typed):
    with pytest.raises(ValueError, match="international format"):
        parse_subject_number(typed, frozenset({"1"}))


def test_bare_stored_digits_are_read_in_the_home_country():
    us_org = frozenset({"1"})
    egyptian = parse_subject_number("+20 2555 0143", us_org)
    assert not egyptian.matches("2025550143")  # a US national number
    assert egyptian.matches("+202 555 0143")
    assert egyptian.matches("00202 555 0143")

    american = parse_subject_number("+1 202 555 0143", us_org)
    assert american.matches("2025550143")
    assert american.matches("12025550143")

    irish = parse_subject_number("+353 87 123 4567", frozenset({"353"}))
    assert irish.matches("353871234567")  # E.164 without "+", home country
    assert not parse_subject_number("+44 7911 123456", frozenset({"353"})).matches(
        "447911123456"
    )


async def test_post_call_marker_is_not_set_when_the_job_is_cancelled(monkeypatch):
    import asyncio

    from api.tasks import run_integrations, workflow_completion

    marked = AsyncMock()
    monkeypatch.setattr(run_integrations, "mark_post_call_done", marked)
    monkeypatch.setattr(
        run_integrations,
        "_run_integrations_post_workflow_run",
        AsyncMock(side_effect=asyncio.CancelledError()),
    )
    with pytest.raises(asyncio.CancelledError):
        await run_integrations.run_integrations_post_workflow_run(None, 5)
    marked.assert_not_awaited()

    monkeypatch.setattr(workflow_completion, "mark_post_call_done", marked)
    monkeypatch.setattr(
        workflow_completion,
        "_process_workflow_completion",
        AsyncMock(side_effect=asyncio.CancelledError()),
    )
    with pytest.raises(asyncio.CancelledError):
        await workflow_completion.process_workflow_completion(None, 6)
    marked.assert_not_awaited()


async def test_export_reports_a_call_still_being_processed(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    just_ended = await make_run(
        async_session,
        storage,
        data.workflow,
        context={"caller_number": SUBJECT},
        age=timedelta(minutes=4),
    )
    settled = await make_run(
        async_session, storage, data.workflow, context={"caller_number": SUBJECT}
    )
    await async_session.commit()

    async with await client_for(data.user, usage_routes.router) as client:
        response = await client.post(
            "/organizations/usage/subject-data/export", json={"number": SUBJECT}
        )

    calls = {call["id"]: call for call in response.json()["calls"]}
    assert calls[just_ended.id]["in_progress"] is True
    assert calls[settled.id]["in_progress"] is False


async def test_archived_recordings_are_purged_by_row_and_ids_stay_reserved(
    db_session, async_session, storage
):
    data = await make_org(async_session)
    archived = WorkflowRecordingModel(
        recording_id="Old12345",
        organization_id=data.org.id,
        transcript="Hello",
        storage_key=f"recordings/{data.org.id}/Old12345/a.wav",
        storage_backend="minio",
        created_by=data.user.id,
        is_active=False,
    )
    active = WorkflowRecordingModel(
        recording_id="New12345",
        organization_id=data.org.id,
        transcript="Hello",
        storage_key=f"recordings/{data.org.id}/New12345/a.wav",
        storage_backend="minio",
        created_by=data.user.id,
    )
    async_session.add_all([archived, active])
    await async_session.commit()

    # An archived ID is still taken: (recording_id, organization) is unique.
    assert await db_client.check_recording_id_exists("Old12345", data.org.id)
    # The user can only delete active recordings; the archived one is the purge's.
    async with await client_for(data.user, recording_routes.router) as client:
        assert (await client.delete("/workflow-recordings/Old12345")).status_code == 404
    # Purging by the archived row's key never reaches an active row.
    assert not await stored_files.delete_archived_workflow_recording(
        organization_id=data.org.id, recording_pk=active.id
    )
    assert await stored_files.delete_archived_workflow_recording(
        organization_id=data.org.id, recording_pk=archived.id
    )
    assert await db_client.get_recording_for_deletion(
        data.org.id, recording_id="New12345", is_active=True
    )


async def test_upload_urls_refuse_file_names_that_leave_the_folder(
    db_session, async_session, storage, monkeypatch
):
    data = await make_org(async_session)
    await async_session.commit()
    monkeypatch.setattr(
        knowledge_base_routes, "_require_document_processing", lambda: None
    )

    async with await client_for(
        data.user, knowledge_base_routes.router, recording_routes.router
    ) as client:
        document = await client.post(
            "/knowledge-base/upload-url",
            json={"filename": "../../9/x.pdf", "mime_type": "application/pdf"},
        )
        recording = await client.post(
            "/workflow-recordings/upload-url",
            json={"files": [{"filename": "a/../b.wav", "file_size": 10}]},
        )

    assert document.status_code == 400
    assert recording.status_code == 400


# --- third review -----------------------------------------------------------------------


async def test_a_late_upload_after_erasure_stores_nothing(
    db_session, async_session, storage, monkeypatch
):
    from api.services import workflow_run_artifacts

    data = await make_org(async_session)
    run = await make_run(
        async_session, storage, data.workflow, context={"caller_number": SUBJECT}
    )
    await async_session.commit()
    await erase_one(data, run)
    monkeypatch.setattr(workflow_run_artifacts, "storage_fs", storage)

    await workflow_run_artifacts.upload_workflow_run_artifacts(
        run.id,
        mixed_audio_wav=b"audio",
        user_audio_wav=b"audio",
        transcript_text="This is Aoife",
    )

    assert storage.objects.keys().isdisjoint(run_keys(run.id))
    await async_session.refresh(run)
    assert run.recording_url is None and run.transcript_url is None


async def test_an_upload_racing_an_erasure_is_deleted_again(
    db_session, async_session, storage, monkeypatch
):
    from api.services import workflow_run_artifacts

    data = await make_org(async_session)
    run = await make_run(async_session, storage, data.workflow, context={})
    await async_session.commit()
    monkeypatch.setattr(workflow_run_artifacts, "storage_fs", storage)
    # Not purged when the upload starts, purged once it has landed.
    monkeypatch.setattr(
        db_client, "is_workflow_run_purged", AsyncMock(side_effect=[False, True])
    )

    await workflow_run_artifacts.upload_workflow_run_artifacts(
        run.id, transcript_text="This is Aoife"
    )

    assert f"transcripts/{run.id}.txt" not in storage.objects


async def test_an_erased_call_gets_no_public_link(db_session, async_session, storage):
    data = await make_org(async_session)
    run = await make_run(async_session, storage, data.workflow, context={})
    run.public_access_token = None
    await async_session.commit()
    await erase_one(data, run)

    assert await db_client.ensure_public_access_token(run.id) is None
    await async_session.refresh(run)
    assert run.public_access_token is None


async def test_webhook_purge_check_locks_the_run(db_session, async_session, storage):
    """The delivery's purge check holds a shared lock on the run row, so an
    erasure's FOR UPDATE scrub serialises with it."""
    from sqlalchemy.dialects import postgresql

    statements = []
    original = async_session.execute

    async def spy(statement, *args, **kwargs):
        statements.append(statement)
        return await original(statement, *args, **kwargs)

    data = await make_org(async_session)
    run = await make_run(async_session, storage, data.workflow, context={})
    await async_session.commit()
    async_session.execute = spy
    try:
        await db_client.create_webhook_delivery(
            workflow_run_id=run.id,
            organization_id=data.org.id,
            endpoint_url="https://crm.example.com/hook",
            payload={"ok": True},
            max_attempts=5,
            webhook_node_id="n1",
        )
    finally:
        del async_session.execute
    sql = str(statements[0].compile(dialect=postgresql.dialect()))
    assert "FOR SHARE OF workflow_runs" in sql
