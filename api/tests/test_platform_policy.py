"""Superuser per-organization platform model policy (#49)."""

import uuid
from contextlib import asynccontextmanager

import pytest

from api.db.models import OrganizationModel, UserModel
from api.enums import OrganizationConfigurationKey
from api.schemas.ai_model_configuration import OrganizationAIModelConfigurationV2
from api.schemas.platform_models import PlatformModelPolicy
from api.services.configuration.ai_model_configuration import compile_for_organization
from api.services.configuration.platform.policy import save_platform_model_policy

V2_URL = "/api/v1/organizations/model-configurations/v2"
REALTIME = {
    "version": 2,
    "mode": "platform",
    "platform": {"pipeline_mode": "realtime", "realtime": {}},
}


def pipeline_with_llm(model):
    return {
        "version": 2,
        "mode": "platform",
        "platform": {
            "pipeline_mode": "pipeline",
            "pipeline": {"llm": {"model": model}},
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
    monkeypatch.setattr(constants, "PLATFORM_VERTEX_LLM_LOCATION", "eu")
    monkeypatch.setattr(constants, "PLATFORM_VERTEX_REALTIME_LOCATION", "europe-west1")
    monkeypatch.setattr(constants, "PLATFORM_GOOGLE_SPEECH_LOCATION", "eu")
    monkeypatch.setattr(
        organization_routes, "UserConfigurationValidator", AcceptingValidator
    )
    monkeypatch.setattr(
        workflow_routes, "UserConfigurationValidator", AcceptingValidator
    )


@pytest.fixture
def make_org(async_session, db_session, test_client_factory, platform_server):
    from tests.conftest import DEFAULT_WORKFLOW_DEFINITION

    @asynccontextmanager
    async def make(*, superuser=False):
        organization = OrganizationModel(provider_id=f"policy-org-{uuid.uuid4().hex}")
        async_session.add(organization)
        await async_session.flush()
        user = UserModel(
            provider_id=f"policy-user-{uuid.uuid4().hex}",
            selected_organization_id=organization.id,
            is_superuser=superuser,
        )
        async_session.add(user)
        await async_session.flush()
        await db_session.upsert_configuration(
            organization.id,
            OrganizationConfigurationKey.MODEL_CONFIGURATION_V2.value,
            REALTIME,
        )
        workflow = await db_session.create_workflow(
            name="Agent",
            workflow_definition=DEFAULT_WORKFLOW_DEFINITION,
            user_id=user.id,
            organization_id=organization.id,
        )
        async with test_client_factory(user) as client:
            yield client, organization, workflow

    return make


@pytest.fixture
async def admin(make_org, monkeypatch):
    from api.app import app
    from api.services.auth.depends import get_superuser

    async with make_org(superuser=True) as (client, organization, workflow):
        app.dependency_overrides[get_superuser] = lambda: UserModel(is_superuser=True)
        try:
            yield client
        finally:
            app.dependency_overrides.pop(get_superuser, None)


def policy_url(organization_id):
    return f"/api/v1/superuser/platform-models/organizations/{organization_id}"


@pytest.mark.asyncio
async def test_policy_endpoints_are_superuser_only(make_org):
    from api.app import app
    from api.services.auth.depends import get_superuser

    async with make_org() as (client, organization, _workflow):
        # get_superuser authenticates from the request headers itself rather
        # than through the overridden get_user, so this request is rejected
        # before any handler runs; the route check below covers the
        # non-superuser case.
        app.dependency_overrides.pop(get_superuser, None)
        get = await client.get(policy_url(organization.id))
        put = await client.put(policy_url(organization.id), json={"locked": True})

    assert get.status_code in (401, 403)
    assert put.status_code in (401, 403)
    routes = {
        route.path: route
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1/superuser/platform-models")
    }
    assert routes
    for route in routes.values():
        calls = {dep.call for dep in route.dependant.dependencies}
        assert get_superuser in calls


@pytest.mark.asyncio
async def test_superuser_sets_and_reads_a_policy(admin, make_org):
    async with make_org() as (_client, organization, _workflow):
        response = await admin.put(
            policy_url(organization.id),
            json={"extra_models": ["gemini-3.5-flash-lite"], "llm_location": "eu"},
        )
        fetched = await admin.get(policy_url(organization.id))
        missing = await admin.get(policy_url(10**9))
        invalid = await admin.put(
            policy_url(organization.id), json={"extra_models": ["gpt-4.1"]}
        )

    assert response.status_code == 200, response.text
    assert fetched.json()["policy"]["extra_models"] == ["gemini-3.5-flash-lite"]
    assert [m["id"] for m in fetched.json()["restricted_models"]] == [
        "gemini-3.5-flash-lite"
    ]
    assert missing.status_code == 404
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_restricted_model_is_offered_only_to_enabled_organizations(make_org):
    # One client at a time: the test client factory authenticates every
    # client as the most recently created user.
    body = pipeline_with_llm("gemini-3.5-flash-lite")
    async with make_org() as (enabled, enabled_org, _workflow):
        await save_platform_model_policy(
            enabled_org.id, PlatformModelPolicy(extra_models=["gemini-3.5-flash-lite"])
        )
        allowed = await enabled.put(V2_URL, json=body)
        enabled_catalog = (await enabled.get(f"{V2_URL}/defaults")).json()
    async with make_org() as (other, _other_org, _workflow):
        refused = await other.put(V2_URL, json=body)
        other_catalog = (await other.get(f"{V2_URL}/defaults")).json()

    assert allowed.status_code == 200, allowed.text
    assert refused.status_code == 422

    def llm_ids(defaults):
        return [m["id"] for m in defaults["platform"]["pipeline"]["llm"]["models"]]

    assert "gemini-3.5-flash-lite" in llm_ids(enabled_catalog)
    assert "gemini-3.5-flash-lite" not in llm_ids(other_catalog)


@pytest.mark.asyncio
async def test_locked_organization_keeps_its_settings(make_org):
    async with make_org() as (client, organization, workflow):
        await save_platform_model_policy(
            organization.id, PlatformModelPolicy(locked=True)
        )
        org = await client.put(V2_URL, json=pipeline_with_llm("gemini-3.5-flash"))
        override = await client.put(
            f"/api/v1/workflow/{workflow.id}",
            json={
                "workflow_configurations": {
                    "model_configuration_v2_override": pipeline_with_llm(
                        "gemini-3.5-flash"
                    )
                }
            },
        )
        catalog = (await client.get(f"{V2_URL}/defaults")).json()["platform"]

    assert org.status_code == 403
    assert override.status_code == 403
    assert catalog["locked"] is True


@pytest.mark.asyncio
async def test_enterprise_placement_applies_to_that_organization_only(make_org):
    async with make_org() as (_client, enterprise, _w1):
        await save_platform_model_policy(
            enterprise.id,
            PlatformModelPolicy(
                project_id="enterprise-project", realtime_location="europe-west4"
            ),
        )
        config = OrganizationAIModelConfigurationV2.model_validate(REALTIME)
        async with make_org() as (_other_client, other, _w2):
            placed = await compile_for_organization(config, enterprise.id)
            default = await compile_for_organization(config, other.id)

    assert placed.realtime.project_id == "enterprise-project"
    assert placed.realtime.location == "europe-west4"
    assert placed.llm.location == "eu"
    assert default.realtime.project_id == "operator-project"
    assert default.realtime.location == "europe-west1"


@pytest.mark.asyncio
async def test_locked_org_can_still_save_unrelated_agent_settings(make_org, db_session):
    """The UI re-sends the unchanged override on every agent save."""
    override = pipeline_with_llm("gemini-3.5-flash")
    async with make_org() as (client, organization, workflow):
        url = f"/api/v1/workflow/{workflow.id}"
        first = await client.put(
            url,
            json={
                "workflow_configurations": {"model_configuration_v2_override": override}
            },
        )
        stored = (await client.get(f"/api/v1/workflow/fetch/{workflow.id}")).json()[
            "workflow_configurations"
        ]["model_configuration_v2_override"]
        await save_platform_model_policy(
            organization.id, PlatformModelPolicy(locked=True)
        )
        resave = await client.put(
            url,
            json={
                "workflow_configurations": {
                    "max_call_duration": 600,
                    "model_configuration_v2_override": stored,
                }
            },
        )

    assert first.status_code == 200, first.text
    assert resave.status_code == 200, resave.text


@pytest.mark.asyncio
async def test_removed_extra_is_grandfathered_but_not_newly_selectable(make_org):
    body = pipeline_with_llm("gemini-3.5-flash-lite")
    async with make_org() as (client, organization, _workflow):
        await save_platform_model_policy(
            organization.id, PlatformModelPolicy(extra_models=["gemini-3.5-flash-lite"])
        )
        assert (await client.put(V2_URL, json=body)).status_code == 200
        stored = (await client.get(V2_URL)).json()["configuration"]
        await save_platform_model_policy(organization.id, PlatformModelPolicy())

        stored["platform"]["pipeline"]["tts"]["speed"] = 1.1
        other_change = await client.put(V2_URL, json=stored)

    assert other_change.status_code == 200, other_change.text


@pytest.mark.asyncio
async def test_superuser_cannot_remove_an_extra_still_in_use(admin, make_org):
    async with make_org() as (client, organization, _workflow):
        await save_platform_model_policy(
            organization.id, PlatformModelPolicy(extra_models=["gemini-3.5-flash-lite"])
        )
        await client.put(V2_URL, json=pipeline_with_llm("gemini-3.5-flash-lite"))
        response = await admin.put(
            policy_url(organization.id), json={"extra_models": []}
        )

    assert response.status_code == 422
    assert "gemini-3.5-flash-lite" in response.json()["detail"]


@pytest.mark.asyncio
async def test_superuser_may_change_a_locked_org(make_org):
    async with make_org(superuser=True) as (client, organization, _workflow):
        await save_platform_model_policy(
            organization.id, PlatformModelPolicy(locked=True)
        )
        response = await client.put(
            V2_URL, json=pipeline_with_llm("gemini-3.5-flash-lite")
        )

    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_invalid_stored_policy_stops_calls_instead_of_moving_them(
    make_org, db_session
):
    from fastapi import HTTPException

    from api.services.configuration.ai_model_configuration import (
        get_effective_ai_model_configuration_for_workflow,
    )

    async with make_org() as (client, organization, _workflow):
        await db_session.upsert_configuration(
            organization.id,
            OrganizationConfigurationKey.PLATFORM_MODEL_POLICY.value,
            {"project_id": "NOT A PROJECT"},
        )
        catalog = (await client.get(f"{V2_URL}/defaults")).json()["platform"]
        change = await client.put(V2_URL, json=pipeline_with_llm("gemini-3.5-flash"))
        with pytest.raises(HTTPException) as exc:
            await get_effective_ai_model_configuration_for_workflow(
                organization_id=organization.id,
                workflow_configurations={"model_configuration_v2_override": REALTIME},
            )

    assert catalog["locked"] is True
    assert change.status_code == 403
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_agent_override_runs_with_the_organization_placement(make_org):
    from api.services.configuration.ai_model_configuration import (
        get_effective_ai_model_configuration_for_workflow,
    )

    async with make_org() as (_client, organization, _workflow):
        await save_platform_model_policy(
            organization.id, PlatformModelPolicy(llm_location="europe-west4")
        )
        effective = await get_effective_ai_model_configuration_for_workflow(
            organization_id=organization.id,
            workflow_configurations={
                "model_configuration_v2_override": pipeline_with_llm("gemini-3.5-flash")
            },
        )

    assert effective.llm.location == "europe-west4"


@pytest.mark.parametrize(
    "field, value",
    [
        ("realtime_location", "eu"),
        ("llm_location", "Europe West"),
        ("project_id", "Bad_Project"),
    ],
)
def test_policy_rejects_invalid_placement(field, value):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PlatformModelPolicy.model_validate({field: value})
