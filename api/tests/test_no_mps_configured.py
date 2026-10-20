"""With MPS_API_URL unset (the default) nothing may be sent to an MPS.

Every MPS-only feature degrades instead: the client refuses before building a
request, hosted-SaaS features answer 404 or empty, knowledge base processing
fails closed and recordings transcribe on the platform's own Speech-to-Text.
"""

import io
import os
import subprocess
import sys
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api import constants
from api.errors.mps import MPSNotConfiguredError
from api.routes import knowledge_base as knowledge_base_routes
from api.routes import organization_usage, service_keys
from api.routes import user as user_routes
from api.routes import workflow as workflow_routes
from api.routes import workflow_recording as recording_routes
from api.schemas.knowledge_base import (
    DocumentUploadRequestSchema,
    ProcessDocumentRequestSchema,
)
from api.services import mps_service_key_client as mps_client_module
from api.services import recording_transcription
from api.services.auth.depends import get_user
from api.services.configuration.registry import ServiceProviders
from api.services.mps_service_key_client import MPSServiceKeyClient, mps_base_url
from api.tasks import knowledge_base_processing

REPO_ROOT = Path(__file__).resolve().parents[2]
USER = SimpleNamespace(
    id=1,
    provider_id="provider-1",
    selected_organization_id=11,
)


@pytest.fixture(autouse=True)
def no_mps(monkeypatch):
    """Whatever the environment says, these tests run without an MPS."""
    monkeypatch.setattr(mps_client_module, "MPS_API_URL", "")
    monkeypatch.setattr(mps_client_module.mps_service_key_client, "base_url", "")


@pytest.fixture
def no_network(monkeypatch):
    """Fail the test if anything tries to send an HTTP request."""

    async def refuse_async(*_args, **_kwargs):
        raise AssertionError("an HTTP request was sent")

    def refuse(*_args, **_kwargs):
        raise AssertionError("an HTTP request was sent")

    monkeypatch.setattr(httpx.AsyncClient, "send", refuse_async)
    monkeypatch.setattr(httpx.Client, "send", refuse)


def test_mps_api_url_defaults_to_unset():
    env = {**os.environ}
    env.pop("MPS_API_URL", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import api.constants as c; print(repr(c.MPS_API_URL), c.MPS_ENABLED)",
        ],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "'' False"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.get_service_keys(created_by="u"),
        lambda c: c.create_service_key(name="k", created_by="u"),
        lambda c: c.get_usage_by_created_by("u"),
        lambda c: c.get_credit_ledger(organization_id=1),
        lambda c: c.get_billing_pricing(1),
        lambda c: c.ensure_billing_account_v2(organization_id=1),
        lambda c: c.ensure_cloudonix_domain(organization_id=1, created_by="u"),
        lambda c: c.create_correlation_id(service_key="sk"),
        lambda c: c.check_service_key_usage("sk"),
        lambda c: c.report_platform_usage(organization_id=1, duration_seconds=1),
        lambda c: c.transcribe_audio(audio_data=b"x"),
        lambda c: c.get_voices(provider="elevenlabs"),
        lambda c: c.call_workflow_api(
            call_type="INBOUND", use_case="u", activity_description="a"
        ),
    ],
)
async def test_client_refuses_before_sending_anything(monkeypatch, no_network, call):
    # Hosted mode, so the OSS-mode guards in the client do not answer first.
    monkeypatch.setattr(mps_client_module, "DEPLOYMENT_MODE", "saas")
    with pytest.raises(MPSNotConfiguredError):
        await call(MPSServiceKeyClient())


@pytest.mark.asyncio
async def test_process_document_is_never_sent(no_network, tmp_path):
    document = tmp_path / "doc.txt"
    document.write_text("private text")
    with pytest.raises(MPSNotConfiguredError):
        await MPSServiceKeyClient().process_document(
            file_path=str(document), filename="doc.txt", content_type="text/plain"
        )


def test_sync_service_key_validation_refuses(no_network):
    with pytest.raises(MPSNotConfiguredError):
        MPSServiceKeyClient().validate_service_key("sk")


def test_managed_model_base_url_refuses():
    with pytest.raises(MPSNotConfiguredError):
        mps_base_url()


@pytest.mark.asyncio
async def test_not_configured_handler_returns_404():
    import json

    from api.app import app, handle_mps_not_configured_error

    assert app.exception_handlers[MPSNotConfiguredError] is (
        handle_mps_not_configured_error
    )
    response = await handle_mps_not_configured_error(None, MPSNotConfiguredError())
    assert response.status_code == 404
    assert json.loads(response.body) == {
        "detail": "This feature isn't available on this server."
    }


@pytest.mark.asyncio
async def test_health_reports_mps_disabled(monkeypatch):
    from api.routes import main as main_routes

    async def endpoints():
        return ("http://localhost:8000", None)

    monkeypatch.setattr("api.utils.common.get_backend_endpoints", endpoints)
    health = await main_routes.health()
    assert health.mps_enabled is False


# Service keys, credits, pricing ------------------------------------------------


@pytest.mark.asyncio
async def test_service_keys_list_is_empty_and_writes_are_404(no_network):
    assert await service_keys.get_service_keys(user=USER) == []

    with pytest.raises(HTTPException) as created:
        await service_keys.create_service_key(
            request=SimpleNamespace(name="k", expires_in_days=90), user=USER
        )
    assert created.value.status_code == 404

    with pytest.raises(HTTPException) as archived:
        await service_keys.archive_service_key(service_key_id="k", user=USER)
    assert archived.value.status_code == 404


@pytest.mark.asyncio
async def test_mps_credits_and_purchase_url_are_404(no_network):
    with pytest.raises(HTTPException) as credits:
        await organization_usage.get_billing_credits(page=1, limit=50, user=USER)
    assert credits.value.status_code == 404

    with pytest.raises(HTTPException) as purchase:
        await organization_usage.create_mps_credit_purchase_url(user=USER)
    assert purchase.value.status_code == 404


@pytest.mark.asyncio
async def test_model_pricing_is_empty(monkeypatch, no_network):
    from api.routes import organization as organization_routes

    monkeypatch.setattr(organization_routes, "DEPLOYMENT_MODE", "saas")
    pricing = await organization_routes.get_model_configuration_pricing(user=USER)
    assert pricing.model_dump(exclude_none=True) == {}


# Voices and the managed provider -------------------------------------------------


@pytest.mark.asyncio
async def test_voice_catalog_is_empty_for_mps_proxied_providers(no_network):
    response = await user_routes.get_voices(provider="elevenlabs", user=USER)
    assert response.provider == "elevenlabs"
    assert response.voices == []


@pytest.mark.asyncio
async def test_managed_provider_is_not_offered(monkeypatch):
    monkeypatch.setattr(user_routes, "customer_keys_allowed", lambda _user: True)
    defaults = await user_routes.get_default_configurations(user=USER)
    for service in ("llm", "tts", "stt", "embeddings"):
        schemas = getattr(defaults, service)
        assert schemas, service
        assert ServiceProviders.DOGRAH.value not in schemas


def test_managed_service_key_fails_validation():
    from api.services.configuration.check_validity import UserConfigurationValidator

    with pytest.raises(ValueError, match="managed models aren't available"):
        UserConfigurationValidator()._check_dograh_api_key("default", "mps_sk_1")


# Agent builder -------------------------------------------------------------------


def test_agent_builder_without_platform_models_is_404(monkeypatch):
    monkeypatch.setattr(workflow_routes.constants, "PLATFORM_MODELS_ENABLED", False)
    call_workflow_api = AsyncMock()
    monkeypatch.setattr(
        workflow_routes.mps_service_key_client, "call_workflow_api", call_workflow_api
    )
    app = FastAPI()
    app.include_router(workflow_routes.router)
    app.dependency_overrides[get_user] = lambda: USER

    response = TestClient(app).post(
        "/workflow/create/template",
        json={
            "call_type": "inbound",
            "use_case": "support",
            "activity_description": "Answer questions",
        },
    )

    assert response.status_code == 404
    assert "Agent Builder isn't available" in response.json()["detail"]
    call_workflow_api.assert_not_awaited()


# Recording transcription ----------------------------------------------------------


def _transcription_app() -> TestClient:
    app = FastAPI()
    app.include_router(recording_routes.router)
    app.dependency_overrides[get_user] = lambda: USER
    return TestClient(app)


def test_transcription_without_platform_models_is_404(monkeypatch, no_network):
    monkeypatch.setattr(
        recording_transcription.constants, "PLATFORM_MODELS_ENABLED", False
    )
    response = _transcription_app().post(
        "/workflow-recordings/transcribe",
        files={"file": ("a.wav", b"RIFF", "audio/wav")},
        data={"language": "en"},
    )
    assert response.status_code == 404


def test_transcription_uses_platform_speech(monkeypatch):
    monkeypatch.setattr(
        recording_transcription.constants, "PLATFORM_MODELS_ENABLED", True
    )
    platform = AsyncMock(return_value={"transcript": "hello there"})
    monkeypatch.setattr(
        recording_transcription, "_transcribe_with_platform_speech", platform
    )
    transcribe_audio = AsyncMock()
    monkeypatch.setattr(
        mps_client_module.mps_service_key_client, "transcribe_audio", transcribe_audio
    )

    response = _transcription_app().post(
        "/workflow-recordings/transcribe",
        files={"file": ("a.wav", b"RIFF", "audio/wav")},
        data={"language": "de-DE"},
    )

    assert response.status_code == 200
    assert response.json() == {"transcript": "hello there"}
    platform.assert_awaited_once_with(b"RIFF", "de-DE", USER.selected_organization_id)
    transcribe_audio.assert_not_awaited()


def _wav(seconds: float, rate: int = 8000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * int(seconds * rate))
    return buffer.getvalue()


def test_wav_duration():
    assert recording_transcription._wav_duration_seconds(_wav(2)) == 2
    assert recording_transcription._wav_duration_seconds(b"not a wav") is None


def test_long_wav_recording_is_not_sent_to_google(monkeypatch):
    monkeypatch.setattr(
        recording_transcription.constants, "PLATFORM_MODELS_ENABLED", True
    )
    platform = AsyncMock(return_value={"transcript": "never"})
    monkeypatch.setattr(
        recording_transcription, "_transcribe_with_platform_speech", platform
    )

    response = _transcription_app().post(
        "/workflow-recordings/transcribe",
        files={"file": ("a.wav", _wav(56), "audio/wav")},
        data={"language": "en"},
    )

    # The same failure the dialog already handles: it asks for a typed transcript.
    assert response.status_code == 500
    assert response.json() == {"detail": "Failed to transcribe audio"}
    platform.assert_not_awaited()


def test_short_wav_recording_is_transcribed(monkeypatch):
    monkeypatch.setattr(
        recording_transcription.constants, "PLATFORM_MODELS_ENABLED", True
    )
    platform = AsyncMock(return_value={"transcript": "hi"})
    monkeypatch.setattr(
        recording_transcription, "_transcribe_with_platform_speech", platform
    )

    response = _transcription_app().post(
        "/workflow-recordings/transcribe",
        files={"file": ("a.wav", _wav(10), "audio/wav")},
        data={"language": "en"},
    )

    assert response.status_code == 200
    platform.assert_awaited_once()


class _FakeSpeechClient:
    instances: list["_FakeSpeechClient"] = []

    def __init__(self, *, credentials, client_options):
        self.client_options = client_options
        self.request = None
        self.closed = False
        _FakeSpeechClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        self.closed = True

    async def recognize(self, *, request):
        self.request = request
        return SimpleNamespace(
            results=[
                SimpleNamespace(alternatives=[SimpleNamespace(transcript=" hello ")])
            ]
        )


@pytest.mark.asyncio
async def test_platform_speech_uses_the_organization_policy(monkeypatch):
    import google.cloud.speech_v2

    from api.services.configuration.platform import policy

    monkeypatch.setattr(constants, "PLATFORM_VERTEX_PROJECT_ID", "server-project")
    monkeypatch.setattr(constants, "PLATFORM_GOOGLE_SPEECH_LOCATION", "eu")
    monkeypatch.setattr(constants, "PLATFORM_GOOGLE_CREDENTIALS_JSON", None)
    get_configuration = AsyncMock(
        return_value=SimpleNamespace(
            value={"project_id": "customer-project", "speech_location": "us"}
        )
    )
    monkeypatch.setattr(policy.db_client, "get_configuration", get_configuration)
    _FakeSpeechClient.instances = []
    monkeypatch.setattr(google.cloud.speech_v2, "SpeechAsyncClient", _FakeSpeechClient)

    result = await recording_transcription._transcribe_with_platform_speech(
        b"audio", "de-DE", 42
    )

    assert result == {"transcript": "hello"}
    assert get_configuration.await_args.args[0] == 42
    (client,) = _FakeSpeechClient.instances
    assert client.client_options.api_endpoint == "us-speech.googleapis.com"
    assert client.request.recognizer == (
        "projects/customer-project/locations/us/recognizers/_"
    )
    assert client.closed


@pytest.mark.parametrize(
    ("language", "expected"),
    [("multi", "auto"), ("en", "auto"), ("", "auto"), ("de-DE", "de-DE")],
)
def test_platform_language_code(language, expected):
    assert recording_transcription._platform_language_code(language) == expected


# Knowledge base -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_knowledge_base_uploads_are_refused(no_network):
    with pytest.raises(HTTPException) as upload:
        await knowledge_base_routes.get_upload_url(
            request=DocumentUploadRequestSchema(
                filename="a.pdf", mime_type="application/pdf"
            ),
            user=USER,
        )
    assert upload.value.status_code == 503
    assert upload.value.detail == "Document processing isn't available yet."

    with pytest.raises(HTTPException) as process:
        await knowledge_base_routes.process_document(
            request=ProcessDocumentRequestSchema(
                document_uuid="u", s3_key="knowledge_base/11/u/a.pdf"
            ),
            user=USER,
        )
    assert process.value.status_code == 503


@pytest.mark.asyncio
async def test_knowledge_base_task_fails_closed(monkeypatch, no_network):
    update_status = AsyncMock()
    download = AsyncMock()
    process_document = AsyncMock()
    monkeypatch.setattr(
        knowledge_base_processing.db_client, "update_document_status", update_status
    )
    monkeypatch.setattr(
        knowledge_base_processing.storage_fs, "adownload_file", download
    )
    monkeypatch.setattr(
        knowledge_base_processing.mps_service_key_client,
        "process_document",
        process_document,
    )

    await knowledge_base_processing.process_knowledge_base_document(
        {}, 5, "knowledge_base/11/u/a.pdf", 11, "provider-1"
    )

    update_status.assert_awaited_once_with(
        5, "failed", error_message="Document processing isn't available yet."
    )
    download.assert_not_awaited()
    process_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_knowledge_base_search_with_managed_embeddings_is_not_a_500(
    monkeypatch, no_network
):
    from api.schemas.knowledge_base import ChunkSearchRequestSchema
    from api.services.configuration import ai_model_configuration

    resolved = SimpleNamespace(
        effective=SimpleNamespace(
            embeddings=SimpleNamespace(
                provider=ServiceProviders.DOGRAH.value,
                api_key="mps_sk_1",
                model="default",
                base_url=None,
            )
        )
    )
    monkeypatch.setattr(
        ai_model_configuration,
        "get_resolved_ai_model_configuration",
        AsyncMock(return_value=resolved),
    )

    # The app-level handler turns this into the clear 404.
    with pytest.raises(MPSNotConfiguredError):
        await knowledge_base_routes.search_chunks(
            request=ChunkSearchRequestSchema(query="hours"), user=USER
        )
