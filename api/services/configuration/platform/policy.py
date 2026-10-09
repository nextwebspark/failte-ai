"""Per-organization platform model policy, set by superusers (#49).

A policy widens what one organization may pick (restricted catalog models),
pins its current choices, or places its calls in another Vertex project or
location for Enterprise customers. Customers never see or edit it.
"""

from __future__ import annotations

from dataclasses import replace

from loguru import logger
from pydantic import ValidationError

from api.db import db_client
from api.enums import OrganizationConfigurationKey
from api.schemas.platform_models import (
    PlatformAIModelConfiguration,
    PlatformModelPolicy,
)
from api.services.configuration.platform import catalog
from api.services.configuration.platform.settings import (
    PlatformModelsNotConfiguredError,
    PlatformVertexSettings,
    load_platform_vertex_settings,
)

_POLICY_KEY = OrganizationConfigurationKey.PLATFORM_MODEL_POLICY.value


class PlatformChoiceNotOfferedError(ValueError):
    """A choice exists in the catalog but is not offered to this organization."""


class PlatformConfigurationLockedError(ValueError):
    """A superuser pinned this organization's model configuration."""


class InvalidPlatformPolicyError(PlatformModelsNotConfiguredError):
    """The stored policy no longer parses.

    Falling back to server defaults could move an Enterprise organization's
    calls to another project or region, so calls stop instead (503) until a
    superuser saves the policy again.
    """


async def get_platform_model_policy(organization_id: int | None) -> PlatformModelPolicy:
    if organization_id is None:
        return PlatformModelPolicy()
    row = await db_client.get_configuration(organization_id, _POLICY_KEY)
    if row is None or not row.value:
        return PlatformModelPolicy()
    try:
        return PlatformModelPolicy.model_validate(row.value)
    except ValidationError as exc:
        logger.error(
            f"Invalid platform model policy for organization {organization_id}"
        )
        raise InvalidPlatformPolicyError(
            f"Invalid platform model policy for organization {organization_id}"
        ) from exc


async def save_platform_model_policy(
    organization_id: int, policy: PlatformModelPolicy
) -> PlatformModelPolicy:
    await db_client.upsert_configuration(
        organization_id, _POLICY_KEY, policy.model_dump(mode="json", exclude_none=True)
    )
    return policy


def platform_settings_for(policy: PlatformModelPolicy) -> PlatformVertexSettings:
    """The server's Vertex settings with the policy's placement applied."""
    settings = load_platform_vertex_settings(project_id=policy.project_id)
    return replace(
        settings,
        llm_location=policy.llm_location or settings.llm_location,
        realtime_location=policy.realtime_location or settings.realtime_location,
        speech_location=policy.speech_location or settings.speech_location,
    )


async def platform_settings_for_organization(
    organization_id: int | None,
) -> PlatformVertexSettings:
    return platform_settings_for(await get_platform_model_policy(organization_id))


async def llm_models_in_use(organization_id: int) -> set[str]:
    """LLM models the organization's configuration and agent overrides use."""
    values: list[object] = []
    row = await db_client.get_configuration(
        organization_id, OrganizationConfigurationKey.MODEL_CONFIGURATION_V2.value
    )
    if row is not None:
        values.append(row.value)
    for workflow in await db_client.list_workflows_for_model_configuration_migration(
        organization_id
    ):
        for configurations in (
            workflow.workflow_configurations,
            *(
                definition.workflow_configurations
                for definition in workflow.definitions
            ),
        ):
            if isinstance(configurations, dict):
                values.append(configurations.get("model_configuration_v2_override"))
    models: set[str] = set()
    for value in values:
        if not isinstance(value, dict) or value.get("mode") != "platform":
            continue
        pipeline = (value.get("platform") or {}).get("pipeline") or {}
        model = (pipeline.get("llm") or {}).get("model")
        if isinstance(model, str):
            models.add(model)
    return models


def offered_llm_models(
    policy: PlatformModelPolicy,
) -> tuple[catalog.PlatformOption, ...]:
    extras = tuple(
        option
        for option in catalog.RESTRICTED_LLM_MODELS
        if option.id in policy.extra_models
    )
    return catalog.LLM_MODELS + extras


def ensure_choices_offered(
    configuration: PlatformAIModelConfiguration,
    policy: PlatformModelPolicy,
    *,
    previous: PlatformAIModelConfiguration | None = None,
) -> None:
    """Raise if *configuration* picks something this organization isn't offered.

    A model the previous configuration already used stays allowed: removing an
    extra from the policy stops new selections but doesn't break saving other
    changes, and configurations that use it keep running.
    """
    if configuration.pipeline is None:
        return
    model = configuration.pipeline.llm.model
    previous_model = (
        previous.pipeline.llm.model
        if previous is not None and previous.pipeline is not None
        else None
    )
    if model == previous_model:
        return
    if model not in catalog.option_ids(offered_llm_models(policy)):
        raise PlatformChoiceNotOfferedError(
            f"LLM model {model!r} is not offered to this organization"
        )
