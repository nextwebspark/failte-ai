"""Catalog integrations: connect a tools-service provider to a workspace.

Install is a saga across two stores, compensated on failure:

1. create the connection in the tools service (it validates the secret and
   config, and stores the secret encrypted);
2. create a bearer credential in the workspace;
3. issue a connection key bound to that credential, and store it as the
   credential's token;
4. create an MCP tool at ``{tools_base_url}/mcp/{provider}`` using the
   credential (``create_tool_for_user`` also discovers its functions).

If any step after (1) fails, the connection is revoked (which revokes its
keys) and the credential is deleted, then the original error is re-raised.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from loguru import logger
from pydantic import JsonValue

from api.db.models import UserModel
from api.errors.integrations import IntegrationNotFoundError
from api.schemas.integrations import (
    InstallIntegrationRequest,
    IntegrationCatalogResponse,
    IntegrationConnection,
    IntegrationConnectionResponse,
    IntegrationProvider,
    IntegrationTestResponse,
)
from api.services.tool_integrations.client import (
    Caller,
    ConnectionTestResult,
    IssuedConnectionKey,
    NewConnection,
)
from api.services.tool_integrations.resources import (
    IntegrationResources,
    LinkedCredential,
    NewMcpTool,
)

_DEFAULT_ICON = "plug"
_MAX_ICON_CHARS = 50


class ToolsServiceApi(Protocol):
    """The subset of ``ToolsServiceClient`` this service uses."""

    async def get_catalog(self, caller: Caller) -> IntegrationCatalogResponse: ...

    async def list_connections(self, caller: Caller) -> list[IntegrationConnection]: ...

    async def get_connection(
        self, caller: Caller, connection_id: uuid.UUID
    ) -> IntegrationConnection: ...

    async def create_connection(
        self, caller: Caller, body: NewConnection
    ) -> IntegrationConnection: ...

    async def update_config(
        self,
        caller: Caller,
        connection_id: uuid.UUID,
        config: Mapping[str, JsonValue],
    ) -> IntegrationConnection: ...

    async def test_connection(
        self, caller: Caller, connection_id: uuid.UUID
    ) -> ConnectionTestResult: ...

    async def issue_key(
        self,
        caller: Caller,
        connection_id: uuid.UUID,
        *,
        fallcha_credential_uuid: str | None,
    ) -> IssuedConnectionKey: ...

    async def revoke_connection(
        self, caller: Caller, connection_id: uuid.UUID
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class Actor:
    """The member acting, in the organization they act in."""

    organization_id: int
    user: UserModel

    @property
    def caller(self) -> Caller:
        return Caller(org_id=self.organization_id, user_id=self.user.id)


@dataclass(slots=True)
class _Links:
    """Workspace resources per connection, for one organization."""

    credential_by_connection: dict[uuid.UUID, str] = field(default_factory=dict)
    tools_by_credential: dict[str, list[str]] = field(default_factory=dict)

    def response(
        self, connection: IntegrationConnection
    ) -> IntegrationConnectionResponse:
        credential_uuid = self.credential_by_connection.get(connection.id)
        tool_uuids = (
            self.tools_by_credential.get(credential_uuid, []) if credential_uuid else []
        )
        return IntegrationConnectionResponse(
            **connection.model_dump(),
            credential_uuid=credential_uuid,
            tool_uuids=list(tool_uuids),
        )


def _credential_name(provider: IntegrationProvider, connection_id: uuid.UUID) -> str:
    # Credential names are unique per org (including deleted ones); the
    # connection id keeps every install distinct.
    return f"{provider.title} integration ({connection_id.hex[:12]})"


def _icon(provider: IntegrationProvider) -> str:
    icon = provider.icon.strip()
    return icon if icon and len(icon) <= _MAX_ICON_CHARS else _DEFAULT_ICON


class IntegrationService:
    def __init__(
        self,
        *,
        tools_service: ToolsServiceApi,
        resources: IntegrationResources,
        tools_base_url: str,
    ) -> None:
        self._tools = tools_service
        self._resources = resources
        self._base_url = tools_base_url.rstrip("/")

    def mcp_url(self, provider_id: str) -> str:
        return f"{self._base_url}/mcp/{provider_id}"

    # -- reads -----------------------------------------------------------

    async def catalog(self, actor: Actor) -> IntegrationCatalogResponse:
        return await self._tools.get_catalog(actor.caller)

    async def list_connections(
        self, actor: Actor
    ) -> list[IntegrationConnectionResponse]:
        connections = await self._tools.list_connections(actor.caller)
        links = await self._links(actor.organization_id)
        return [links.response(c) for c in connections]

    # -- writes ----------------------------------------------------------

    async def install(
        self, actor: Actor, request: InstallIntegrationRequest
    ) -> IntegrationConnectionResponse:
        provider = await self._provider(actor, request.provider)
        connection = await self._tools.create_connection(
            actor.caller,
            NewConnection(
                provider=provider.id,
                auth_mode=request.auth_mode,
                secret=request.secret,
                account_label=request.account_label,
                scopes_granted=request.scopes_granted,
                config=request.config,
            ),
        )
        credential_uuid: str | None = None
        try:
            credential_uuid = await self._resources.create_credential(
                organization_id=actor.organization_id,
                user_id=actor.user.id,
                name=_credential_name(provider, connection.id),
                description=f"Connection key for the {provider.title} integration. "
                "Managed by Integrations.",
                provider=provider.id,
                connection_id=connection.id,
            )
            issued = await self._tools.issue_key(
                actor.caller, connection.id, fallcha_credential_uuid=credential_uuid
            )
            await self._resources.store_connection_key(
                organization_id=actor.organization_id,
                credential_uuid=credential_uuid,
                provider=provider.id,
                connection_id=connection.id,
                key=issued.key.get_secret_value(),
            )
            tool_uuid = await self._resources.create_mcp_tool(
                user=actor.user,
                tool=NewMcpTool(
                    name=request.tool_name or provider.title,
                    description=provider.description or None,
                    icon=_icon(provider),
                    url=self.mcp_url(provider.id),
                    credential_uuid=credential_uuid,
                ),
            )
        except Exception as exc:
            logger.warning(
                f"Installing {provider.id} for org {actor.organization_id} failed "
                f"({type(exc).__name__}); rolling back connection {connection.id}"
            )
            await self._compensate(actor, connection.id, credential_uuid)
            raise

        logger.info(
            f"Installed {provider.id} for org {actor.organization_id}: "
            f"connection {connection.id}, tool {tool_uuid}"
        )
        return IntegrationConnectionResponse(
            **connection.model_dump(),
            credential_uuid=credential_uuid,
            tool_uuids=[tool_uuid],
        )

    async def update_config(
        self,
        actor: Actor,
        connection_id: uuid.UUID,
        config: Mapping[str, JsonValue],
    ) -> IntegrationConnectionResponse:
        connection = await self._tools.update_config(
            actor.caller, connection_id, config
        )
        return (await self._links(actor.organization_id)).response(connection)

    async def test(
        self, actor: Actor, connection_id: uuid.UUID
    ) -> IntegrationTestResponse:
        result = await self._tools.test_connection(actor.caller, connection_id)
        links = await self._links(actor.organization_id)
        return IntegrationTestResponse(
            ok=result.ok,
            message=result.message,
            connection=links.response(result.connection),
        )

    async def uninstall(self, actor: Actor, connection_id: uuid.UUID) -> None:
        """Revoke the connection first, so its key stops working even if the
        local cleanup fails; retrying is safe (revoke is idempotent)."""
        linked = [
            c
            for c in await self._resources.list_linked_credentials(
                actor.organization_id
            )
            if c.connection_id == connection_id
        ]
        try:
            await self._tools.revoke_connection(actor.caller, connection_id)
        except IntegrationNotFoundError:
            # Unknown to the tools service (e.g. its data was reset): still
            # clean up this org's leftovers, else report the 404.
            if not linked:
                raise
        await self._remove_local(actor.organization_id, linked)
        logger.info(
            f"Uninstalled connection {connection_id} for org {actor.organization_id}"
        )

    # -- helpers ---------------------------------------------------------

    async def _provider(self, actor: Actor, provider_id: str) -> IntegrationProvider:
        catalog = await self._tools.get_catalog(actor.caller)
        for provider in catalog.providers:
            if provider.id == provider_id:
                return provider
        raise IntegrationNotFoundError(f"Unknown integration provider {provider_id!r}")

    async def _links(self, organization_id: int) -> _Links:
        credentials = await self._resources.list_linked_credentials(organization_id)
        return _Links(
            credential_by_connection={
                c.connection_id: c.credential_uuid for c in credentials
            },
            tools_by_credential=await self._resources.mcp_tools_by_credential(
                organization_id
            ),
        )

    async def _remove_local(
        self, organization_id: int, linked: Sequence[LinkedCredential]
    ) -> None:
        if not linked:
            return
        tools_by_credential = await self._resources.mcp_tools_by_credential(
            organization_id
        )
        for credential in linked:
            for tool_uuid in tools_by_credential.get(credential.credential_uuid, []):
                await self._resources.archive_tool(
                    organization_id=organization_id, tool_uuid=tool_uuid
                )
            await self._resources.delete_credential(
                organization_id=organization_id,
                credential_uuid=credential.credential_uuid,
            )

    async def _compensate(
        self, actor: Actor, connection_id: uuid.UUID, credential_uuid: str | None
    ) -> None:
        """Best-effort rollback; failures are logged, never raised, so the
        caller sees the original error."""
        try:
            await self._tools.revoke_connection(actor.caller, connection_id)
        except Exception as exc:  # noqa: BLE001 - rollback is best-effort
            logger.error(
                f"Rollback could not revoke connection {connection_id} for org "
                f"{actor.organization_id}: {type(exc).__name__}"
            )
        if credential_uuid is None:
            return
        try:
            await self._resources.delete_credential(
                organization_id=actor.organization_id, credential_uuid=credential_uuid
            )
        except Exception as exc:  # noqa: BLE001 - rollback is best-effort
            logger.error(
                f"Rollback could not delete credential {credential_uuid} for org "
                f"{actor.organization_id}: {type(exc).__name__}"
            )
