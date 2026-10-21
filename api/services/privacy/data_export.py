"""Account and organisation data exports (GDPR Art. 15 and 20).

Exports are JSON documents a person can read and take elsewhere. They carry
what was put into the product, with every secret removed (API keys, provider
credentials, password hashes, sign-in links), and never call content: call
recordings, transcripts and caller details are not part of an organisation
export. Rows come from ``DataExportClient``, which selects columns explicitly.
"""

import re
from datetime import UTC, datetime
from typing import Any

from api.constants import APP_VERSION
from api.db import db_client
from api.db.models import UserModel
from api.services.configuration.ai_model_configuration import (
    get_organization_ai_model_configuration_v2,
    mask_ai_model_configuration_v2,
)
from api.services.configuration.masking import (
    mask_workflow_configurations,
    mask_workflow_definition,
)
from api.services.organization_preferences import get_organization_preferences
from api.services.user_onboarding import get_onboarding_state

EXPORT_FORMAT_VERSION = 1
REDACTED = "[redacted]"

_SECRET_KEY = re.compile(
    r"(secret|token|password|passwd|api[_-]?key|private[_-]?key|authorization"
    r"|credential|signing[_-]?key|auth[_-]?header)",
    re.IGNORECASE,
)


def redact_secrets(value: Any) -> Any:
    """Copy of ``value`` with the value of every secret-looking key replaced.

    For free-form JSON (tool definitions, call-event sinks) whose secret fields
    are not declared anywhere else.
    """
    if isinstance(value, dict):
        return {
            key: (
                REDACTED
                if isinstance(key, str)
                and _SECRET_KEY.search(key)
                and value[key] not in (None, "", [], {})
                else redact_secrets(value[key])
            )
            for key in value
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def _envelope(kind: str) -> dict[str, Any]:
    return {
        "export": kind,
        "format_version": EXPORT_FORMAT_VERSION,
        "app_version": APP_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
    }


async def export_user_data(user: UserModel) -> dict[str, Any]:
    """The signed-in user's profile, memberships and onboarding progress."""
    profile = await db_client.export_user_profile(user.id) or {}
    memberships = await db_client.list_user_organizations(user.id)
    onboarding = await get_onboarding_state(user.id)
    return {
        **_envelope("account"),
        "profile": profile,
        "memberships": [
            {
                "organization_id": m.organization_id,
                "organization_name": m.name,
                "role": m.role.value,
            }
            for m in memberships
        ],
        "onboarding": onboarding.model_dump(mode="json"),
    }


async def _organization_settings(organization_id: int) -> dict[str, Any]:
    preferences = (await get_organization_preferences(organization_id)).model_dump(
        mode="json"
    )
    if preferences.get("call_events"):
        preferences["call_events"] = redact_secrets(preferences["call_events"])
    model_configuration = mask_ai_model_configuration_v2(
        await get_organization_ai_model_configuration_v2(organization_id),
        drop_secrets=True,
    )
    return {
        "preferences": preferences,
        "model_configuration": model_configuration,
    }


async def export_organization_data(organization_id: int) -> dict[str, Any]:
    """Everything the organisation keeps in the product, minus secrets and
    call content."""
    records = await db_client.export_organization_records(organization_id)
    members = await db_client.list_organization_members(organization_id)

    definitions_by_workflow: dict[int, list[dict[str, Any]]] = {}
    for definition in records.pop("workflow_definitions"):
        definition["workflow_json"] = mask_workflow_definition(
            definition.get("workflow_json"), drop_secrets=True
        )
        definition["workflow_configurations"] = mask_workflow_configurations(
            definition.get("workflow_configurations"), drop_secrets=True
        )
        definitions_by_workflow.setdefault(definition["workflow_id"], []).append(
            definition
        )
    agents = [
        {**workflow, "definitions": definitions_by_workflow.get(workflow["id"], [])}
        for workflow in records.pop("workflows")
    ]
    tools = [
        {**tool, "definition": redact_secrets(tool.get("definition"))}
        for tool in records.pop("tools")
    ]
    organization = records.pop("organization")
    billing_account = records.pop("billing_account")

    return {
        **_envelope("organization"),
        "organization": organization[0] if organization else None,
        "settings": await _organization_settings(organization_id),
        "members": [
            {
                "user_id": m.user_id,
                "email": m.email,
                "name": m.name,
                "role": m.role.value,
                "joined_at": m.joined_at,
            }
            for m in members
        ],
        "agents": agents,
        "tools": tools,
        "billing_account": billing_account[0] if billing_account else None,
        **records,
    }
