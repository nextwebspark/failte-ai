"""Platform-managed models: choices compile onto the operator's Vertex project."""

import copy
import json
import uuid

import pytest
from pydantic import ValidationError

from api.db.models import OrganizationModel, UserModel
from api.schemas.ai_model_configuration import (
    OrganizationAIModelConfigurationV2,
    compile_ai_model_configuration_v2,
)
from api.schemas.platform_models import default_platform_configuration
from api.services.configuration.ai_model_configuration import (
    mask_ai_model_configuration_v2,
    merge_ai_model_configuration_v2_secrets,
)
from api.services.configuration.masking import mask_user_config
from api.services.configuration.platform import settings as platform_settings
from api.services.configuration.platform.settings import (
    PlatformModelsNotConfiguredError,
    PlatformVertexSettings,
)
from api.services.configuration.registry import (
    GoogleSTTConfiguration,
    GoogleTTSConfiguration,
    GoogleVertexLLMConfiguration,
    GoogleVertexRealtimeLLMConfiguration,
)

SETTINGS = PlatformVertexSettings(
    project_id="operator-project",
    llm_location="eu",
    realtime_location="europe-west1",
    speech_location="eu",
)

REALTIME_CONFIG = {
    "version": 2,
    "mode": "platform",
    "platform": {
        "pipeline_mode": "realtime",
        "realtime": {
            "model": "google/gemini-live-2.5-flash-native-audio",
            "voice": "Kore",
            "language": "de",
        },
    },
}

PIPELINE_CONFIG = {
    "version": 2,
    "mode": "platform",
    "platform": {
        "pipeline_mode": "pipeline",
        "pipeline": {
            "llm": {"model": "gemini-3.1-flash-lite", "temperature": 0.3},
            "stt": {"model": "latest_long", "language": "en-GB"},
            "tts": {
                "model": "chirp_3_hd",
                "voice": "en-GB-Chirp3-HD-Aoede",
                "language": "en-GB",
                "speed": 1.1,
            },
        },
    },
}


@pytest.fixture
def operator_settings(monkeypatch):
    """Server settings as the routes read them (no injected settings)."""
    from api import constants

    monkeypatch.setattr(constants, "PLATFORM_VERTEX_PROJECT_ID", "operator-project")
    monkeypatch.setattr(constants, "PLATFORM_VERTEX_LLM_LOCATION", "eu")
    monkeypatch.setattr(constants, "PLATFORM_VERTEX_REALTIME_LOCATION", "europe-west1")
    monkeypatch.setattr(constants, "PLATFORM_GOOGLE_SPEECH_LOCATION", "eu")
    monkeypatch.setattr(constants, "PLATFORM_GOOGLE_CREDENTIALS_JSON", None)
    monkeypatch.setattr(constants, "PLATFORM_MODELS_ENABLED", True)


def test_realtime_choice_compiles_to_vertex_live_with_server_settings():
    config = OrganizationAIModelConfigurationV2.model_validate(REALTIME_CONFIG)

    effective = compile_ai_model_configuration_v2(config, platform_settings=SETTINGS)

    assert effective.is_realtime is True
    assert effective.platform_managed is True
    assert isinstance(effective.realtime, GoogleVertexRealtimeLLMConfiguration)
    assert effective.realtime.voice == "Kore"
    assert effective.realtime.language == "de"
    assert effective.realtime.project_id == "operator-project"
    assert effective.realtime.location == "europe-west1"
    assert effective.realtime.credentials is None
    # Post-call extraction and QA still need a text model.
    assert isinstance(effective.llm, GoogleVertexLLMConfiguration)
    assert effective.llm.model == "gemini-3.5-flash"
    assert effective.llm.location == "eu"
    assert effective.stt is None and effective.tts is None


def test_pipeline_choice_compiles_to_google_stt_vertex_llm_and_google_tts():
    config = OrganizationAIModelConfigurationV2.model_validate(PIPELINE_CONFIG)

    effective = compile_ai_model_configuration_v2(config, platform_settings=SETTINGS)

    assert effective.is_realtime is False
    assert effective.realtime is None
    assert isinstance(effective.llm, GoogleVertexLLMConfiguration)
    assert effective.llm.model == "gemini-3.1-flash-lite"
    assert effective.llm.temperature == 0.3
    assert effective.llm.project_id == "operator-project"
    assert effective.llm.location == "eu"
    assert isinstance(effective.stt, GoogleSTTConfiguration)
    assert (effective.stt.model, effective.stt.language) == ("latest_long", "en-GB")
    assert effective.stt.location == "eu"
    assert isinstance(effective.tts, GoogleTTSConfiguration)
    assert effective.tts.voice == "en-GB-Chirp3-HD-Aoede"
    assert effective.tts.speed == 1.1
    assert effective.tts.location == "eu"


def test_realtime_mode_uses_the_stored_pipeline_llm_choice_for_post_call_work():
    config = OrganizationAIModelConfigurationV2.model_validate(
        {
            **REALTIME_CONFIG,
            "platform": {
                **REALTIME_CONFIG["platform"],
                "pipeline": PIPELINE_CONFIG["platform"]["pipeline"],
            },
        }
    )

    effective = compile_ai_model_configuration_v2(config, platform_settings=SETTINGS)

    assert effective.is_realtime is True
    assert effective.llm.model == "gemini-3.1-flash-lite"
    assert effective.stt is None and effective.tts is None


def test_server_credentials_json_is_injected_at_compile_time():
    settings = PlatformVertexSettings(
        project_id="operator-project",
        llm_location="eu",
        realtime_location="europe-west1",
        speech_location="eu",
        credentials_json='{"type": "service_account"}',
    )
    config = OrganizationAIModelConfigurationV2.model_validate(PIPELINE_CONFIG)

    effective = compile_ai_model_configuration_v2(config, platform_settings=settings)

    assert effective.llm.credentials == settings.credentials_json
    assert effective.stt.credentials == settings.credentials_json
    assert effective.tts.credentials == settings.credentials_json


def test_compile_reads_server_settings_by_default(operator_settings):
    config = OrganizationAIModelConfigurationV2.model_validate(REALTIME_CONFIG)

    effective = compile_ai_model_configuration_v2(config)

    assert effective.realtime.project_id == "operator-project"


def test_compile_fails_loudly_without_a_server_project(monkeypatch):
    monkeypatch.setattr(platform_settings.constants, "PLATFORM_VERTEX_PROJECT_ID", "")
    config = OrganizationAIModelConfigurationV2.model_validate(REALTIME_CONFIG)

    with pytest.raises(PlatformModelsNotConfiguredError):
        compile_ai_model_configuration_v2(config)


@pytest.mark.parametrize(
    "path, value",
    [
        (("realtime", "model"), "gemini-3.8-live"),
        (("realtime", "voice"), "Ghost"),
        (("realtime", "language"), "xx"),
    ],
)
def test_realtime_choices_must_come_from_the_catalog(path, value):
    data = json.loads(json.dumps(REALTIME_CONFIG))
    data["platform"][path[0]][path[1]] = value

    with pytest.raises(ValidationError, match="not offered"):
        OrganizationAIModelConfigurationV2.model_validate(data)


@pytest.mark.parametrize(
    "section, field, value",
    [
        # MaaS models run in us-central1, outside the EU.
        ("llm", "model", "meta/llama-4-maverick-17b-128e-instruct-maas"),
        ("stt", "model", "nova-3"),
        ("stt", "language", "xx-XX"),
        ("tts", "model", "neural2"),
    ],
)
def test_pipeline_choices_must_come_from_the_catalog(section, field, value):
    data = json.loads(json.dumps(PIPELINE_CONFIG))
    data["platform"]["pipeline"][section][field] = value

    with pytest.raises(ValidationError):
        OrganizationAIModelConfigurationV2.model_validate(data)


def test_stt_language_must_be_served_by_the_chosen_model():
    data = json.loads(json.dumps(PIPELINE_CONFIG))
    # Chirp 3 serves Welsh at the eu endpoint; latest_long does not.
    data["platform"]["pipeline"]["stt"] = {"model": "chirp_3", "language": "cy-GB"}
    OrganizationAIModelConfigurationV2.model_validate(data)

    data["platform"]["pipeline"]["stt"]["model"] = "latest_long"
    with pytest.raises(ValidationError, match="not offered on platform models"):
        OrganizationAIModelConfigurationV2.model_validate(data)


def test_vertex_eu_location_resolves_to_the_eu_multi_region_endpoint():
    """Gemini 3.x is served at location "eu" only through the multi-region
    endpoint. Older google-genai releases built eu-aiplatform.googleapis.com,
    which Google rejects, so pin the behaviour of the installed client."""
    from google.auth.credentials import AnonymousCredentials
    from google.genai import Client

    client = Client(
        vertexai=True,
        project="operator-project",
        location="eu",
        credentials=AnonymousCredentials(),
    )

    assert "aiplatform.eu.rep.googleapis.com" in (
        client._api_client._http_options.base_url
    )


@pytest.mark.parametrize(
    "voice",
    ["en-GB-Neural2-A", "en-US-Chirp3-HD-Aoede", "Aoede", "en-GB-Chirp3-HD-"],
)
def test_tts_voice_must_be_a_chirp3_voice_in_the_chosen_language(voice):
    data = json.loads(json.dumps(PIPELINE_CONFIG))
    data["platform"]["pipeline"]["tts"]["voice"] = voice

    with pytest.raises(ValidationError):
        OrganizationAIModelConfigurationV2.model_validate(data)


@pytest.mark.parametrize(
    "section, secret",
    [
        ("realtime", "credentials"),
        ("realtime", "project_id"),
        ("realtime", "location"),
        ("realtime", "api_key"),
    ],
)
def test_platform_config_cannot_carry_keys_or_infrastructure(section, secret):
    data = json.loads(json.dumps(REALTIME_CONFIG))
    data["platform"][section][secret] = "anything"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        OrganizationAIModelConfigurationV2.model_validate(data)


def test_selected_block_is_required():
    with pytest.raises(ValidationError, match="platform.pipeline is required"):
        OrganizationAIModelConfigurationV2.model_validate(
            {"mode": "platform", "platform": {"pipeline_mode": "pipeline"}}
        )
    with pytest.raises(ValidationError, match="platform configuration is required"):
        OrganizationAIModelConfigurationV2.model_validate({"mode": "platform"})


def test_default_platform_configuration_is_gemini_live_charon_english():
    config = default_platform_configuration()

    assert config.pipeline_mode == "realtime"
    assert config.realtime is not None
    assert config.realtime.model == "google/gemini-3.8-live"
    assert config.realtime.voice == "Charon"
    assert config.realtime.language == "en"


@pytest.mark.parametrize(
    ("model", "location"),
    [
        # Gemini 3.x Live is served from the multi-region endpoint.
        ("google/gemini-3.8-live", "eu"),
        # 2.5 native audio only from single regions.
        ("google/gemini-live-2.5-flash-native-audio", "europe-west1"),
    ],
)
def test_realtime_model_runs_where_vertex_serves_it(model, location):
    config = copy.deepcopy(REALTIME_CONFIG)
    config["platform"]["realtime"]["model"] = model
    effective = compile_ai_model_configuration_v2(
        OrganizationAIModelConfigurationV2.model_validate(config),
        platform_settings=SETTINGS,
    )

    assert effective.realtime.model == model
    assert effective.realtime.location == location


def test_masked_effective_config_hides_operator_infrastructure():
    settings = PlatformVertexSettings(
        project_id="operator-project",
        llm_location="eu",
        realtime_location="europe-west1",
        speech_location="eu",
        credentials_json='{"private_key": "secret"}',
    )
    config = OrganizationAIModelConfigurationV2.model_validate(PIPELINE_CONFIG)
    effective = compile_ai_model_configuration_v2(config, platform_settings=settings)

    masked = json.dumps(mask_user_config(effective))

    assert "operator-project" not in masked
    assert "private_key" not in masked
    assert '"location"' not in masked
    assert "gemini-3.1-flash-lite" in masked


def test_platform_config_round_trips_through_mask_and_merge_unchanged():
    config = OrganizationAIModelConfigurationV2.model_validate(PIPELINE_CONFIG)
    existing = OrganizationAIModelConfigurationV2.model_validate(REALTIME_CONFIG)

    assert mask_ai_model_configuration_v2(config) == config.model_dump(
        mode="json", exclude_none=True
    )
    assert merge_ai_model_configuration_v2_secrets(config, existing) == config


# --- HTTP -------------------------------------------------------------------


@pytest.fixture
async def org_client(async_session, test_client_factory, operator_settings):
    organization = OrganizationModel(provider_id=f"platform-org-{uuid.uuid4().hex}")
    async_session.add(organization)
    await async_session.flush()
    user = UserModel(
        provider_id=f"platform-user-{uuid.uuid4().hex}",
        selected_organization_id=organization.id,
    )
    async_session.add(user)
    await async_session.flush()
    async with test_client_factory(user) as client:
        yield client


@pytest.mark.asyncio
async def test_defaults_include_the_platform_catalog(org_client):
    response = await org_client.get(
        "/api/v1/organizations/model-configurations/v2/defaults"
    )

    assert response.status_code == 200
    platform = response.json()["platform"]
    assert [mode["id"] for mode in platform["modes"]] == ["realtime", "pipeline"]
    assert platform["default_mode"] == "realtime"
    assert platform["realtime"]["defaults"] == {
        "model": "google/gemini-3.8-live",
        "voice": "Charon",
        "language": "en",
    }
    voices = {voice["id"]: voice for voice in platform["realtime"]["voices"]}
    # Every Gemini Live voice, each with a sample.
    assert len(voices) == 30
    assert {"Charon", "Kore", "Zephyr", "Sulafat"} <= set(voices)
    assert all(voice["preview_url"] and voice["gender"] for voice in voices.values())
    assert voices["Kore"]["preview_url"].endswith("voice_id=en-US-Chirp3-HD-Kore")
    llm_models = [model["id"] for model in platform["pipeline"]["llm"]["models"]]
    assert llm_models == ["gemini-3.5-flash", "gemini-3.1-flash-lite"]
    assert not any(model.endswith("-maas") for model in llm_models)
    assert platform["pipeline"]["tts"]["voice_catalog"] == "google"
    # BYOK stays available to the hidden editors.
    assert "byok" in response.json() and "dograh" in response.json()


@pytest.mark.asyncio
async def test_saved_platform_config_never_exposes_operator_infrastructure(
    org_client, monkeypatch
):
    from api.routes import organization as organization_routes

    validated = []

    class RecordingValidator:
        async def validate(self, effective, **_kwargs):
            validated.append(effective)

    monkeypatch.setattr(
        organization_routes, "UserConfigurationValidator", RecordingValidator
    )

    response = await org_client.put(
        "/api/v1/organizations/model-configurations/v2", json=PIPELINE_CONFIG
    )
    assert response.status_code == 200, response.text
    assert validated[0].llm.project_id == "operator-project"

    fetched = await org_client.get("/api/v1/organizations/model-configurations/v2")
    body = fetched.json()
    assert body["source"] == "organization_v2"
    assert body["configuration"] == PIPELINE_CONFIG
    assert "operator-project" not in fetched.text
    assert body["effective_configuration"]["llm"]["model"] == "gemini-3.1-flash-lite"
    assert "location" not in body["effective_configuration"]["stt"]


@pytest.mark.asyncio
async def test_saving_a_platform_config_with_a_key_is_rejected(org_client):
    data = json.loads(json.dumps(REALTIME_CONFIG))
    data["platform"]["realtime"]["credentials"] = '{"private_key": "x"}'

    response = await org_client.put(
        "/api/v1/organizations/model-configurations/v2", json=data
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_health_reports_platform_models_flag(org_client, monkeypatch):
    from api import constants

    monkeypatch.setattr(constants, "PLATFORM_MODELS_ENABLED", True)

    response = await org_client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["platform_models_enabled"] is True


@pytest.fixture
async def platform_org_workflow(
    async_session, db_session, test_client_factory, operator_settings, monkeypatch
):
    from tests.conftest import DEFAULT_WORKFLOW_DEFINITION

    from api.enums import OrganizationConfigurationKey
    from api.routes import workflow as workflow_routes

    class AcceptingValidator:
        async def validate(self, effective, **_kwargs):
            return None

    monkeypatch.setattr(
        workflow_routes, "UserConfigurationValidator", AcceptingValidator
    )

    organization = OrganizationModel(provider_id=f"platform-org-{uuid.uuid4().hex}")
    async_session.add(organization)
    await async_session.flush()
    user = UserModel(
        provider_id=f"platform-user-{uuid.uuid4().hex}",
        selected_organization_id=organization.id,
    )
    async_session.add(user)
    await async_session.flush()
    await db_session.upsert_configuration(
        organization.id,
        OrganizationConfigurationKey.MODEL_CONFIGURATION_V2.value,
        REALTIME_CONFIG,
    )
    workflow = await db_session.create_workflow(
        name="Platform agent",
        workflow_definition=DEFAULT_WORKFLOW_DEFINITION,
        user_id=user.id,
        organization_id=organization.id,
    )
    async with test_client_factory(user) as client:
        yield client, workflow


@pytest.mark.asyncio
async def test_workflow_can_override_with_platform_choices(platform_org_workflow):
    client, workflow = platform_org_workflow

    response = await client.put(
        f"/api/v1/workflow/{workflow.id}",
        json={
            "workflow_configurations": {
                "model_configuration_v2_override": PIPELINE_CONFIG
            }
        },
    )

    assert response.status_code == 200, response.text
    assert "operator-project" not in response.text


@pytest.mark.asyncio
async def test_workflow_legacy_overrides_are_rejected_on_platform_orgs(
    platform_org_workflow,
):
    client, workflow = platform_org_workflow

    response = await client.put(
        f"/api/v1/workflow/{workflow.id}",
        json={
            "workflow_configurations": {
                "model_overrides": {"llm": {"model": "gemini-3.5-pro"}}
            }
        },
    )

    assert response.status_code == 403
    assert "platform models" in response.json()["detail"]


@pytest.mark.asyncio
async def test_platform_config_is_refused_while_platform_models_are_off(
    org_client, monkeypatch
):
    from api import constants

    monkeypatch.setattr(constants, "PLATFORM_MODELS_ENABLED", False)

    response = await org_client.put(
        "/api/v1/organizations/model-configurations/v2", json=REALTIME_CONFIG
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_workflow_platform_override_is_refused_while_platform_models_are_off(
    platform_org_workflow, monkeypatch
):
    from api import constants

    client, workflow = platform_org_workflow
    monkeypatch.setattr(constants, "PLATFORM_MODELS_ENABLED", False)

    response = await client.put(
        f"/api/v1/workflow/{workflow.id}",
        json={
            "workflow_configurations": {
                "model_configuration_v2_override": PIPELINE_CONFIG
            }
        },
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_legacy_user_configuration_cannot_rewrite_platform_services(
    platform_org_workflow,
):
    client, _workflow = platform_org_workflow

    response = await client.put(
        "/api/v1/user/configurations/user",
        json={"stt": {"provider": "google", "model": "latest_long"}},
    )

    assert response.status_code == 403
    fetched = await client.get("/api/v1/organizations/model-configurations/v2")
    assert fetched.json()["configuration"] == REALTIME_CONFIG


@pytest.mark.asyncio
async def test_legacy_user_configuration_still_updates_preferences(
    platform_org_workflow,
):
    client, _workflow = platform_org_workflow

    response = await client.put(
        "/api/v1/user/configurations/user", json={"timezone": "Europe/Dublin"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["timezone"] == "Europe/Dublin"
    assert "operator-project" not in response.text


@pytest.mark.asyncio
async def test_runtime_ignores_stored_legacy_overrides_on_platform_orgs(
    monkeypatch, operator_settings
):
    from api.services.configuration import ai_model_configuration
    from api.services.configuration.ai_model_configuration import (
        ResolvedAIModelConfiguration,
        get_effective_ai_model_configuration_for_workflow,
    )

    config = OrganizationAIModelConfigurationV2.model_validate(PIPELINE_CONFIG)
    effective = compile_ai_model_configuration_v2(config)

    async def resolved(**_kwargs):
        return ResolvedAIModelConfiguration(
            effective=effective,
            source="organization_v2",
            organization_configuration=config,
        )

    monkeypatch.setattr(
        ai_model_configuration, "get_resolved_ai_model_configuration", resolved
    )

    result = await get_effective_ai_model_configuration_for_workflow(
        organization_id=1,
        workflow_configurations={
            "model_overrides": {
                "llm": {"model": "meta/llama-4-maverick-maas", "location": "us"}
            }
        },
    )

    assert result.llm.model == "gemini-3.1-flash-lite"
    assert result.llm.location == "eu"


@pytest.mark.asyncio
async def test_platform_org_on_unconfigured_server_stays_usable(
    monkeypatch, operator_settings
):
    from api import constants
    from api.services.configuration import ai_model_configuration
    from api.services.configuration.ai_model_configuration import (
        get_effective_ai_model_configuration_for_workflow,
        get_resolved_ai_model_configuration,
    )

    class Row:
        value = REALTIME_CONFIG
        last_validated_at = None

    async def row(_organization_id):
        return Row()

    monkeypatch.setattr(
        ai_model_configuration, "_get_organization_ai_model_configuration_v2_row", row
    )
    monkeypatch.setattr(constants, "PLATFORM_VERTEX_PROJECT_ID", "")

    resolved = await get_resolved_ai_model_configuration(organization_id=1)

    assert resolved.source == "organization_v2"
    assert resolved.effective.platform_managed is True
    assert resolved.effective.realtime is None

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await get_effective_ai_model_configuration_for_workflow(
            organization_id=1,
            workflow_configurations={
                "model_configuration_v2_override": REALTIME_CONFIG
            },
        )
    assert exc.value.status_code == 503
