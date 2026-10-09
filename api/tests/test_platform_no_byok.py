"""On platform-models servers customers cannot store keys or providers (#47)."""

import uuid

import pytest

from api.db.models import OrganizationModel, UserModel
from api.enums import OrganizationConfigurationKey

BYOK_PIPELINE = {
    "version": 2,
    "mode": "byok",
    "byok": {
        "mode": "pipeline",
        "pipeline": {
            "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-secret"},
            "stt": {
                "provider": "deepgram",
                "model": "nova-3",
                "language": "en",
                "api_key": "dg-secret",
            },
            "tts": {
                "provider": "elevenlabs",
                "model": "eleven_flash_v2_5",
                "voice": "Rachel",
                "api_key": "el-secret",
            },
        },
    },
}
DOGRAH = {"version": 2, "mode": "dograh", "dograh": {"api_key": "mps-secret"}}
PLATFORM = {
    "version": 2,
    "mode": "platform",
    "platform": {
        "pipeline_mode": "realtime",
        "realtime": {
            "model": "google/gemini-live-2.5-flash-native-audio",
            "voice": "Aoede",
            "language": "fr",
        },
    },
}


class AcceptingValidator:
    async def validate(self, effective, **_kwargs):
        return None


@pytest.fixture
def platform_server(monkeypatch):
    from api import constants
    from api.routes import organization as organization_routes
    from api.routes import workflow as workflow_routes

    monkeypatch.setattr(constants, "PLATFORM_MODELS_ENABLED", True)
    monkeypatch.setattr(constants, "PLATFORM_VERTEX_PROJECT_ID", "operator-project")
    monkeypatch.setattr(
        organization_routes, "UserConfigurationValidator", AcceptingValidator
    )
    monkeypatch.setattr(
        workflow_routes, "UserConfigurationValidator", AcceptingValidator
    )


@pytest.fixture
def make_client(async_session, db_session, test_client_factory, platform_server):
    """Client for a fresh org whose stored configuration is *stored*."""
    from contextlib import asynccontextmanager

    from tests.conftest import DEFAULT_WORKFLOW_DEFINITION

    @asynccontextmanager
    async def make(stored, *, superuser=False):
        organization = OrganizationModel(provider_id=f"byok-org-{uuid.uuid4().hex}")
        async_session.add(organization)
        await async_session.flush()
        user = UserModel(
            provider_id=f"byok-user-{uuid.uuid4().hex}",
            selected_organization_id=organization.id,
            is_superuser=superuser,
        )
        async_session.add(user)
        await async_session.flush()
        if stored is not None:
            await db_session.upsert_configuration(
                organization.id,
                OrganizationConfigurationKey.MODEL_CONFIGURATION_V2.value,
                stored,
            )
        workflow = await db_session.create_workflow(
            name="Agent",
            workflow_definition=DEFAULT_WORKFLOW_DEFINITION,
            user_id=user.id,
            organization_id=organization.id,
        )
        async with test_client_factory(user) as client:
            yield client, workflow

    return make


V2_URL = "/api/v1/organizations/model-configurations/v2"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [BYOK_PIPELINE, DOGRAH])
async def test_customer_cannot_store_providers_or_keys(make_client, body):
    async with make_client(PLATFORM) as (client, _workflow):
        response = await client.put(V2_URL, json=body)

        assert response.status_code == 403
        stored = (await client.get(V2_URL)).json()["configuration"]
    assert stored == PLATFORM


@pytest.mark.asyncio
async def test_customer_can_still_change_mode_voice_and_language(make_client):
    async with make_client(PLATFORM) as (client, _workflow):
        changed = {
            **PLATFORM,
            "platform": {
                "pipeline_mode": "realtime",
                "realtime": {**PLATFORM["platform"]["realtime"], "voice": "Puck"},
            },
        }
        response = await client.put(V2_URL, json=changed)

    assert response.status_code == 200, response.text
    assert response.json()["configuration"]["platform"]["realtime"]["voice"] == "Puck"


@pytest.mark.asyncio
async def test_superuser_can_still_store_byok(make_client):
    async with make_client(PLATFORM, superuser=True) as (client, _workflow):
        response = await client.put(V2_URL, json=BYOK_PIPELINE)

    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_responses_carry_no_keys_not_even_masked(make_client):
    # An org migrated late still holds keys; none may reach the browser.
    async with make_client(BYOK_PIPELINE) as (client, workflow):
        org_response = await client.get(V2_URL)
        user_response = await client.get("/api/v1/user/configurations/user")

    for response in (org_response, user_response):
        assert response.status_code == 200, response.text
        assert "secret" not in response.text
        assert "api_key" not in response.text


@pytest.mark.asyncio
async def test_defaults_omit_provider_schemas_for_customers(make_client):
    async with make_client(PLATFORM) as (client, _workflow):
        body = (await client.get(f"{V2_URL}/defaults")).json()

    assert body["platform"]["enabled"] is True
    assert body["dograh"] is None and body["byok"] is None


@pytest.mark.asyncio
async def test_workflow_cannot_override_with_providers_or_keys(make_client):
    async with make_client(PLATFORM) as (client, workflow):
        url = f"/api/v1/workflow/{workflow.id}"
        v2 = await client.put(
            url,
            json={
                "workflow_configurations": {
                    "model_configuration_v2_override": BYOK_PIPELINE
                }
            },
        )
        legacy = await client.put(
            url,
            json={
                "workflow_configurations": {
                    "model_overrides": {
                        "llm": {"provider": "openai", "api_key": "sk-x"}
                    }
                }
            },
        )
        allowed = await client.put(
            url,
            json={
                "workflow_configurations": {"model_configuration_v2_override": PLATFORM}
            },
        )

    assert v2.status_code == 403
    assert legacy.status_code == 403
    assert allowed.status_code == 200, allowed.text


@pytest.mark.asyncio
async def test_legacy_user_configuration_cannot_set_keys(make_client):
    async with make_client(BYOK_PIPELINE) as (client, _workflow):
        response = await client.put(
            "/api/v1/user/configurations/user",
            json={"llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-x"}},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("section", ["dograh", "byok"])
async def test_keys_cannot_ride_along_with_a_platform_choice(make_client, section):
    body = {
        **PLATFORM,
        section: (DOGRAH if section == "dograh" else BYOK_PIPELINE)[section],
    }
    async with make_client(PLATFORM) as (client, workflow):
        org = await client.put(V2_URL, json=body)
        override = await client.put(
            f"/api/v1/workflow/{workflow.id}",
            json={"workflow_configurations": {"model_configuration_v2_override": body}},
        )

    assert org.status_code == 403
    assert override.status_code == 403


@pytest.mark.asyncio
async def test_superuser_round_trip_keeps_stored_keys(make_client):
    async with make_client(BYOK_PIPELINE, superuser=True) as (client, _workflow):
        fetched = (await client.get(V2_URL)).json()["configuration"]
        assert "sk-secret" not in str(fetched)  # masked, not shown
        response = await client.put(V2_URL, json=fetched)

    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_workflow_responses_carry_no_keys(make_client, db_session):
    async with make_client(PLATFORM) as (client, workflow):
        await db_session.bulk_update_workflow_model_configurations(
            organization_id=workflow.organization_id,
            workflow_updates=[
                (
                    workflow.id,
                    {
                        "model_configuration_v2_override": BYOK_PIPELINE,
                        "model_overrides": {"llm": {"api_key": "legacy-secret"}},
                    },
                )
            ],
            definition_updates=[],
        )
        response = await client.get(f"/api/v1/workflow/fetch/{workflow.id}")

    assert response.status_code == 200, response.text
    assert "secret" not in response.text


@pytest.mark.asyncio
async def test_customers_can_still_update_preferences(make_client):
    async with make_client(PLATFORM) as (client, _workflow):
        response = await client.put(
            "/api/v1/user/configurations/user",
            json={"timezone": "Europe/Dublin", "test_phone_number": "+353851234567"},
        )

    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_user_defaults_omit_provider_schemas_for_customers(make_client):
    async with make_client(PLATFORM) as (client, _workflow):
        body = (await client.get("/api/v1/user/configurations/defaults")).json()

    assert body["llm"] == {} and body["tts"] == {} and body["realtime"] == {}
    assert body["workflow_configurations"]


@pytest.mark.asyncio
async def test_qa_node_own_llm_is_ignored_on_platform_servers(monkeypatch):
    from types import SimpleNamespace

    from api.services.workflow.qa import llm_config

    monkeypatch.setattr(llm_config.constants, "PLATFORM_MODELS_ENABLED", True)
    own_llm = []
    monkeypatch.setattr(
        llm_config,
        "create_llm_service_from_provider",
        lambda *args, **kwargs: own_llm.append(args),
    )
    qa = SimpleNamespace(
        qa_use_workflow_llm=False,
        qa_provider="openai",
        qa_model="gpt-4.1",
        qa_api_key="sk-qa",
        qa_endpoint=None,
    )

    result = await llm_config.create_qa_llm_service(qa, workflow_run=None)

    assert own_llm == []
    assert result is None  # no run to resolve the platform LLM from
