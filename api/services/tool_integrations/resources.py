"""Workspace-side resources an installed integration owns: one bearer
credential holding the connection key, and the MCP tool(s) using it.

The link back to the tools-service connection is recorded inside the
credential's ``credential_data`` under ``fallcha_integration`` (beside the
bearer ``token``). That needs no migration, survives edits to the tool (which
re-validate and would drop unknown definition fields), and is never returned
by the credentials API.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from api.db import db_client
from api.db.models import UserModel
from api.enums import ToolCategory, WebhookCredentialType
from api.errors.integrations import IntegrationConflictError, IntegrationToolError
from api.schemas.tool import CreateToolRequest, McpToolConfig, McpToolDefinition
from api.services.tool_management import ToolManagementError, create_tool_for_user

INTEGRATION_METADATA_KEY = "fallcha_integration"


@dataclass(frozen=True, slots=True)
class LinkedCredential:
    credential_uuid: str
    connection_id: uuid.UUID
    provider: str


@dataclass(frozen=True, slots=True)
class NewMcpTool:
    name: str
    description: str | None
    icon: str | None
    url: str
    credential_uuid: str


class IntegrationResources(Protocol):
    async def create_credential(
        self,
        *,
        organization_id: int,
        user_id: int,
        name: str,
        description: str,
        provider: str,
        connection_id: uuid.UUID,
    ) -> str: ...

    async def store_connection_key(
        self,
        *,
        organization_id: int,
        credential_uuid: str,
        provider: str,
        connection_id: uuid.UUID,
        key: str,
    ) -> None: ...

    async def delete_credential(
        self, *, organization_id: int, credential_uuid: str
    ) -> None: ...

    async def list_linked_credentials(
        self, organization_id: int, *, include_deleted: bool = False
    ) -> list[LinkedCredential]: ...

    async def mcp_tools_by_credential(
        self, organization_id: int
    ) -> dict[str, list[str]]: ...

    async def create_mcp_tool(self, *, user: UserModel, tool: NewMcpTool) -> str: ...

    async def archive_tool(self, *, organization_id: int, tool_uuid: str) -> None: ...


def _credential_data(
    *, token: str, provider: str, connection_id: uuid.UUID
) -> dict[str, Any]:
    return {
        "token": token,
        INTEGRATION_METADATA_KEY: {
            "provider": provider,
            "connection_id": str(connection_id),
        },
    }


def _linked(credential_uuid: str, data: object) -> LinkedCredential | None:
    if not isinstance(data, dict):
        return None
    meta = data.get(INTEGRATION_METADATA_KEY)
    if not isinstance(meta, dict):
        return None
    provider, raw_id = meta.get("provider"), meta.get("connection_id")
    if not isinstance(provider, str) or not isinstance(raw_id, str):
        return None
    try:
        connection_id = uuid.UUID(raw_id)
    except ValueError:
        return None
    return LinkedCredential(
        credential_uuid=credential_uuid,
        connection_id=connection_id,
        provider=provider,
    )


def is_integration_managed(credential_data: object) -> bool:
    """True for a credential an installed integration owns. Such credentials
    are changed or removed only through the integrations API."""
    return (
        isinstance(credential_data, dict)
        and INTEGRATION_METADATA_KEY in credential_data
    )


def _mcp_credential_uuid(definition: object) -> str | None:
    if not isinstance(definition, dict):
        return None
    config = definition.get("config")
    if not isinstance(config, dict):
        return None
    value = config.get("credential_uuid")
    return value if isinstance(value, str) and value else None


class DbIntegrationResources:
    """``IntegrationResources`` backed by the Fallcha database."""

    async def create_credential(
        self,
        *,
        organization_id: int,
        user_id: int,
        name: str,
        description: str,
        provider: str,
        connection_id: uuid.UUID,
    ) -> str:
        # The token is filled in by store_connection_key once the tools
        # service has issued a key bound to this credential's uuid.
        credential = await db_client.create_credential(
            organization_id=organization_id,
            user_id=user_id,
            name=name,
            description=description,
            credential_type=WebhookCredentialType.BEARER_TOKEN.value,
            credential_data=_credential_data(
                token="", provider=provider, connection_id=connection_id
            ),
        )
        return str(credential.credential_uuid)

    async def store_connection_key(
        self,
        *,
        organization_id: int,
        credential_uuid: str,
        provider: str,
        connection_id: uuid.UUID,
        key: str,
    ) -> None:
        updated = await db_client.update_credential(
            credential_uuid=credential_uuid,
            organization_id=organization_id,
            credential_data=_credential_data(
                token=key, provider=provider, connection_id=connection_id
            ),
        )
        if updated is None:
            raise IntegrationConflictError(
                "The integration's credential was removed while installing"
            )

    async def delete_credential(
        self, *, organization_id: int, credential_uuid: str
    ) -> None:
        await db_client.delete_credential(credential_uuid, organization_id)

    async def list_linked_credentials(
        self, organization_id: int, *, include_deleted: bool = False
    ) -> list[LinkedCredential]:
        credentials = await db_client.get_credentials_for_organization(
            organization_id, active_only=not include_deleted
        )
        linked = (
            _linked(str(c.credential_uuid), c.credential_data) for c in credentials
        )
        return [item for item in linked if item is not None]

    async def mcp_tools_by_credential(
        self, organization_id: int
    ) -> dict[str, list[str]]:
        tools = await db_client.get_tools_for_organization(
            organization_id, category=ToolCategory.MCP.value
        )
        by_credential: dict[str, list[str]] = {}
        for tool in tools:
            credential_uuid = _mcp_credential_uuid(tool.definition)
            if credential_uuid:
                by_credential.setdefault(credential_uuid, []).append(
                    str(tool.tool_uuid)
                )
        return by_credential

    async def create_mcp_tool(self, *, user: UserModel, tool: NewMcpTool) -> str:
        request = CreateToolRequest(
            name=tool.name,
            description=tool.description,
            category=ToolCategory.MCP.value,
            icon=tool.icon,
            definition=McpToolDefinition(
                type="mcp",
                config=McpToolConfig(
                    url=tool.url, credential_uuid=tool.credential_uuid
                ),
            ),
        )
        try:
            created = await create_tool_for_user(request, user, source="integration")
        except ToolManagementError as exc:
            raise IntegrationToolError(
                exc.message, status_code=exc.status_code
            ) from exc
        return created.tool_uuid

    async def archive_tool(self, *, organization_id: int, tool_uuid: str) -> None:
        await db_client.archive_tool(tool_uuid, organization_id)
