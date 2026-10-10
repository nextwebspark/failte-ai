"""Moving existing organizations onto platform models (#46)."""

import copy
import importlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from api.db.models import OrganizationModel, UserModel
from api.enums import OrganizationConfigurationKey
from api.schemas.ai_model_configuration import OrganizationAIModelConfigurationV2
from api.services.configuration.platform.migration import (
    migrate_to_platform,
    migrate_workflow_configurations,
)

DOGRAH = {
    "version": 2,
    "mode": "dograh",
    "dograh": {
        "api_key": "mps-secret",
        "voice": "default",
        "language": "de",
        "temperature": 0.4,
    },
}

BYOK_GOOGLE_PIPELINE = {
    "version": 2,
    "mode": "byok",
    "byok": {
        "mode": "pipeline",
        "pipeline": {
            "llm": {
                "provider": "google_vertex",
                "model": "gemini-3.1-flash-lite",
                "project_id": "customer-project",
                "location": "global",
                "credentials": '{"private_key": "customer"}',
            },
            "stt": {"provider": "google", "model": "latest_long", "language": "en-GB"},
            "tts": {
                "provider": "google",
                "model": "chirp_3_hd",
                "voice": "en-GB-Chirp3-HD-Kore",
                "speed": 1.2,
            },
        },
    },
}

BYOK_OPENAI_PIPELINE = {
    "version": 2,
    "mode": "byok",
    "byok": {
        "mode": "pipeline",
        "pipeline": {
            "llm": {"provider": "openai", "model": "gpt-4.1", "api_key": "sk-x"},
            "stt": {
                "provider": "deepgram",
                "model": "nova-3",
                "language": "fr",
                "api_key": "dg",
            },
            "tts": {
                "provider": "elevenlabs",
                "model": "eleven_flash_v2_5",
                "voice": "Rachel",
                "api_key": "el",
            },
        },
    },
}

BYOK_REALTIME_VERTEX = {
    "version": 2,
    "mode": "byok",
    "byok": {
        "mode": "realtime",
        "realtime": {
            "realtime": {
                "provider": "google_vertex_realtime",
                "model": "google/gemini-live-2.5-flash-native-audio",
                "voice": "Puck",
                "language": "es",
                "project_id": "customer-project",
                "location": "global",
            },
            "llm": {
                "provider": "google_vertex",
                "model": "gemini-3.5-flash",
                "project_id": "customer-project",
                "location": "global",
            },
        },
    },
}


def _migrate(stored):
    return migrate_to_platform(
        OrganizationAIModelConfigurationV2.model_validate(stored)
    )


def test_dograh_org_moves_to_gemini_live_keeping_language_and_temperature():
    result = _migrate(DOGRAH)

    config = result.configuration
    assert config.pipeline_mode == "realtime"
    assert (config.realtime.voice, config.realtime.language) == ("Charon", "de")
    assert config.pipeline.llm.temperature == 0.4
    assert result.notes


def test_byok_google_pipeline_keeps_its_choices_without_keys():
    result = _migrate(BYOK_GOOGLE_PIPELINE)

    config = result.configuration
    assert config.pipeline_mode == "pipeline"
    assert config.pipeline.llm.model == "gemini-3.1-flash-lite"
    assert (config.pipeline.stt.model, config.pipeline.stt.language) == (
        "latest_long",
        "en-GB",
    )
    assert config.pipeline.tts.voice == "en-GB-Chirp3-HD-Kore"
    assert config.pipeline.tts.language == "en-GB"
    assert config.pipeline.tts.speed == 1.2
    dumped = config.model_dump_json()
    assert "customer-project" not in dumped and "private_key" not in dumped


def test_byok_pipeline_without_a_google_voice_moves_to_gemini_live():
    result = _migrate(BYOK_OPENAI_PIPELINE)

    config = result.configuration
    assert config.pipeline_mode == "realtime"
    # The caller spoke French to Deepgram; Gemini Live keeps speaking French.
    assert config.realtime.language == "fr"
    assert (config.pipeline.stt.model, config.pipeline.stt.language) == (
        "chirp_3",
        "fr-FR",
    )
    assert config.pipeline.llm.model == "gemini-3.5-flash"
    assert any("gpt-4.1" in note for note in result.notes)
    assert any("deepgram" in note for note in result.notes)


@pytest.mark.parametrize(
    "model, language, expected",
    [
        # Chirp 3 does not serve Igbo at the eu endpoint; latest_long does.
        ("chirp_3", "ig-NG", ("latest_long", "ig-NG")),
        # An unknown model falls back to the default, then to one serving es-CO.
        ("chirp_2", "es-CO", ("latest_long", "es-CO")),
        # A bare language code maps to the language's home locale.
        ("latest_long", "de", ("latest_long", "de-DE")),
        ("chirp_3", "xx-XX", ("chirp_3", "en-GB")),
    ],
)
def test_google_stt_language_is_kept_with_a_model_that_serves_it(
    model, language, expected
):
    stored = json.loads(json.dumps(BYOK_GOOGLE_PIPELINE))
    stored["byok"]["pipeline"]["stt"].update(model=model, language=language)

    result = _migrate(stored)

    stt = result.configuration.pipeline.stt
    assert (stt.model, stt.language) == expected


def test_dograh_org_without_temperature_gets_the_platform_default():
    stored = json.loads(json.dumps(DOGRAH))
    del stored["dograh"]["temperature"]

    result = _migrate(stored)

    assert result.configuration.pipeline.llm.temperature == 0.1


def test_unparsable_workflow_override_is_replaced_by_the_default():
    migrated, notes = migrate_workflow_configurations(
        {"model_configuration_v2_override": {"mode": "byok", "byok": {"mode": "x"}}}
    )

    assert migrated["model_configuration_v2_override"]["mode"] == "platform"
    assert any("unparsable" in note for note in notes)


def test_byok_vertex_realtime_keeps_voice_and_language():
    result = _migrate(BYOK_REALTIME_VERTEX)

    config = result.configuration
    assert (config.realtime.voice, config.realtime.language) == ("Puck", "es")
    # The Live model the organization ran is kept, not swapped for the default.
    assert config.realtime.model == "google/gemini-live-2.5-flash-native-audio"
    assert config.pipeline.llm.model == "gemini-3.5-flash"
    assert result.notes == []


def test_byok_gemini_api_live_model_maps_onto_the_vertex_catalog_id():
    realtime = copy.deepcopy(BYOK_REALTIME_VERTEX)
    service = realtime["byok"]["realtime"]["realtime"]
    service.update(provider="google_realtime", model="gemini-3.8-live", api_key="k")
    for key in ("project_id", "location", "credentials"):
        service.pop(key, None)

    result = _migrate(realtime)

    assert result.configuration.realtime.model == "google/gemini-3.8-live"


def test_workflow_override_and_legacy_overlay_are_migrated():
    migrated, notes = migrate_workflow_configurations(
        {
            "max_call_duration": 600,
            "model_overrides": {"llm": {"model": "gpt-4.1"}},
            "model_configuration_v2_override": BYOK_GOOGLE_PIPELINE,
        }
    )

    assert "model_overrides" not in migrated
    assert migrated["max_call_duration"] == 600
    override = migrated["model_configuration_v2_override"]
    assert override["mode"] == "platform"
    assert override["platform"]["pipeline"]["tts"]["voice"] == "en-GB-Chirp3-HD-Kore"
    assert "legacy model_overrides removed" in notes


def test_workflow_without_overrides_or_already_platform_is_unchanged():
    assert migrate_workflow_configurations({"max_call_duration": 600}) is None
    assert migrate_workflow_configurations(None) is None
    platform = {
        "model_configuration_v2_override": {
            "version": 2,
            "mode": "platform",
            "platform": {"pipeline_mode": "realtime", "realtime": {}},
        }
    }
    normalized = OrganizationAIModelConfigurationV2.model_validate(
        platform["model_configuration_v2_override"]
    ).model_dump(mode="json", exclude_none=True)
    assert (
        migrate_workflow_configurations({"model_configuration_v2_override": normalized})
        is None
    )


# --- Script: plan, apply, revert ---------------------------------------------


@pytest.fixture
def script():
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root))
    try:
        yield importlib.import_module("scripts.migrate_orgs_to_platform_models")
    finally:
        sys.path.remove(str(repo_root))


@pytest.mark.asyncio
async def test_script_migrates_and_reverts_an_organization_exactly(
    script, async_session, db_session
):
    from tests.conftest import DEFAULT_WORKFLOW_DEFINITION

    organization = OrganizationModel(provider_id=f"migrate-org-{uuid.uuid4().hex}")
    async_session.add(organization)
    await async_session.flush()
    user = UserModel(
        provider_id=f"migrate-user-{uuid.uuid4().hex}",
        selected_organization_id=organization.id,
    )
    async_session.add(user)
    await async_session.flush()
    key = OrganizationConfigurationKey.MODEL_CONFIGURATION_V2.value
    await db_session.upsert_configuration(organization.id, key, DOGRAH)
    workflow = await db_session.create_workflow(
        name="Migrated agent",
        workflow_definition=DEFAULT_WORKFLOW_DEFINITION,
        user_id=user.id,
        organization_id=organization.id,
    )
    workflow_configs = {
        "max_call_duration": 600,
        "model_configuration_v2_override": BYOK_GOOGLE_PIPELINE,
    }
    await db_session.bulk_update_workflow_model_configurations(
        organization_id=organization.id,
        workflow_updates=[(workflow.id, workflow_configs)],
        definition_updates=[],
    )

    plans = await script.build_plans({organization.id})
    assert len(plans) == 1
    backup = script.backup_record(plans[0])
    await script.apply_plan(plans[0])

    migrated = (await db_session.get_configuration(organization.id, key)).value
    assert migrated["mode"] == "platform"
    assert "mps-secret" not in str(migrated)
    stored_workflow = await db_session.get_workflow(
        workflow.id, organization_id=organization.id
    )
    override = stored_workflow.workflow_configurations[
        "model_configuration_v2_override"
    ]
    assert override["mode"] == "platform"
    # A second run finds nothing left to do.
    assert await script.build_plans({organization.id}) == []

    await script.revert(backup)

    assert (await db_session.get_configuration(organization.id, key)).value == DOGRAH
    restored = await db_session.get_workflow(
        workflow.id, organization_id=organization.id
    )
    assert restored.workflow_configurations == workflow_configs


@pytest.mark.asyncio
async def test_script_dry_run_writes_nothing_and_apply_requires_a_backup(
    script, monkeypatch, tmp_path, capsys
):
    plan = script.OrganizationPlan(organization_id=7, before=DOGRAH, after={})
    monkeypatch.setattr(script, "build_plans", AsyncMock(return_value=[plan]))
    apply_plan = AsyncMock()
    monkeypatch.setattr(script, "apply_plan", apply_plan)

    monkeypatch.setattr(sys, "argv", ["migrate"])
    assert await script.main() == 0
    apply_plan.assert_not_awaited()

    monkeypatch.setattr(sys, "argv", ["migrate", "--apply"])
    with pytest.raises(SystemExit):
        await script.main()
    apply_plan.assert_not_awaited()

    backup = tmp_path / "backup.jsonl"
    monkeypatch.setattr(sys, "argv", ["migrate", "--apply", "--backup", str(backup)])
    assert await script.main() == 0
    apply_plan.assert_awaited_once_with(plan)
    assert backup.stat().st_mode & 0o777 == 0o600
    assert json.loads(backup.read_text())["model_configuration_v2"] == DOGRAH
    # Never overwrite an earlier backup: it is the only full restore point.
    with pytest.raises(FileExistsError):
        await script.main()
    assert "mps-secret" not in capsys.readouterr().out


def test_platform_models_refuse_mps_billing_at_startup():
    env = {
        **os.environ,
        "PLATFORM_MODELS_ENABLED": "true",
        "PLATFORM_VERTEX_PROJECT_ID": "operator-project",
        "BILLING_PROVIDER": "mps",
    }
    result = subprocess.run(
        [sys.executable, "-c", "import api.constants"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "BILLING_PROVIDER" in result.stderr


@pytest.mark.asyncio
async def test_legacy_migrate_endpoint_is_closed_on_platform_servers(
    async_session, test_client_factory, monkeypatch
):
    from api import constants

    monkeypatch.setattr(constants, "PLATFORM_MODELS_ENABLED", True)
    organization = OrganizationModel(provider_id=f"migrate-org-{uuid.uuid4().hex}")
    async_session.add(organization)
    await async_session.flush()
    user = UserModel(
        provider_id=f"migrate-user-{uuid.uuid4().hex}",
        selected_organization_id=organization.id,
    )
    async_session.add(user)
    await async_session.flush()

    async with test_client_factory(user) as client:
        response = await client.post(
            "/api/v1/organizations/model-configurations/v2/migrate?force=true"
        )

    assert response.status_code == 409
