"""Catalog integrations: connect a tools-service provider to a workspace.

A connection is created in the tools service either from directly supplied
secrets (``install``) or by the OAuth2 callback (``start_oauth`` sends the
user to the provider first). Activating it is a saga across two stores,
compensated on failure:

1. create a bearer credential in the workspace;
2. issue the connection's key (exclusively: a connection is activated at
   most once), bound to that credential, and store it as the token;
3. create an MCP tool at ``{tools_base_url}/mcp/{provider}`` using the
   credential (``create_tool_for_user`` also discovers its functions).

``install`` = create the connection + activate; if activation fails the
connection is revoked (which revokes its keys). ``activate`` on an existing
(OAuth) connection keeps the connection on failure, so it can be retried,
and revokes only the key it issued. Either way the credential is deleted and
the original error re-raised.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from loguru import logger
from pydantic import JsonValue

from api.db.models import UserModel
from api.errors.integrations import (
    IntegrationConflictError,
    IntegrationNotFoundError,
)
from api.schemas.integrations import (
    CreateProviderAppRequest,
    InstallIntegrationRequest,
    IntegrationCatalogResponse,
    IntegrationConnection,
    IntegrationConnectionResponse,
    IntegrationProvider,
    IntegrationTestResponse,
    ProviderAppListResponse,
    ProviderAppResponse,
    StartOAuthRequest,
)
from api.services.tool_integrations.client import (
    Caller,
    ConnectionTestResult,
    IssuedConnectionKey,
    NewConnection,
    StartedOAuth,
)
from api.services.tool_integrations.resources import (
    IntegrationResources,
    LinkedCredential,
    NewMcpTool,
)

_DEFAULT_ICON = "plug"
CONFIRM_IN_SAME_BROWSER = (
    "Finish connecting in the browser where you started, as the same user, "
    "within 10 minutes"
)
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
        exclusive: bool = False,
    ) -> IssuedConnectionKey: ...

    async def revoke_key(
        self, caller: Caller, connection_id: uuid.UUID, key_id: uuid.UUID
    ) -> None: ...

    async def revoke_all_keys(
        self, caller: Caller, connection_id: uuid.UUID
    ) -> None: ...

    async def confirm_connection(
        self, caller: Caller, connection_id: uuid.UUID, *, browser_nonce: str
    ) -> IntegrationConnection: ...

    async def revoke_connection(
        self, caller: Caller, connection_id: uuid.UUID
    ) -> None: ...

    async def list_provider_apps(self, caller: Caller) -> ProviderAppListResponse: ...

    async def create_provider_app(
        self, caller: Caller, body: CreateProviderAppRequest
    ) -> ProviderAppResponse: ...

    async def delete_provider_app(self, caller: Caller, app_id: uuid.UUID) -> None: ...

    async def start_oauth(
        self, caller: Caller, body: StartOAuthRequest
    ) -> StartedOAuth: ...


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
    # Credential names are unique per org (including deleted ones). The
    # connection id keeps installs apart; the random part keeps attempts
    # apart, so a failed (rolled back) or concurrent activation of the same
    # connection never collides with an earlier credential's name.
    return (
        f"{provider.title} integration "
        f"({connection_id.hex[:12]}-{secrets.token_hex(3)})"
    )


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
        # Thin on purpose: the route depends only on this service, which owns
        # the actor -> tools-service identity mapping and client wiring.
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
        """Create a connection from direct secrets, then activate it."""
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
        return await self._activate(
            actor,
            provider,
            connection,
            tool_name=request.tool_name,
            keep_connection_on_failure=False,
        )

    async def activate(
        self,
        actor: Actor,
        connection_id: uuid.UUID,
        *,
        tool_name: str | None,
        browser_nonce: str | None,
    ) -> IntegrationConnectionResponse:
        """Install an existing connection as an MCP tool. Idempotent: an
        already-activated connection is returned as it is.

        A PENDING (just-authorized OAuth) connection is first confirmed with
        ``browser_nonce``, returned by :meth:`start_oauth` to the
        starting user's browser; the tools service also checks the user.
        """
        # Org-scoped by the tools service: another org's connection is a 404.
        connection = await self._tools.get_connection(actor.caller, connection_id)
        links = await self._links(actor.organization_id)
        if connection.id in links.credential_by_connection:
            return links.response(connection)
        if connection.status == "revoked":
            raise IntegrationConflictError("This connection has been removed")
        if connection.status == "pending":
            if not browser_nonce:
                raise IntegrationConflictError(CONFIRM_IN_SAME_BROWSER)
            connection = await self._tools.confirm_connection(
                actor.caller, connection.id, browser_nonce=browser_nonce
            )
        provider = await self._provider(actor, connection.provider)
        for attempt in range(2):
            try:
                return await self._activate(
                    actor,
                    provider,
                    connection,
                    tool_name=tool_name,
                    keep_connection_on_failure=True,
                )
            except IntegrationConflictError:
                # A concurrent activation won the exclusive key: return its
                # result.
                links = await self._links(actor.organization_id)
                if connection.id in links.credential_by_connection:
                    return links.response(connection)
                if attempt:
                    raise
                # No credential holds the live key: it was orphaned by an
                # activation whose rollback failed. Revoke it and retry once.
                logger.warning(
                    f"Revoking orphaned keys of connection {connection.id} for "
                    f"org {actor.organization_id}"
                )
                await self._tools.revoke_all_keys(actor.caller, connection.id)
        raise AssertionError("unreachable")

    async def _activate(
        self,
        actor: Actor,
        provider: IntegrationProvider,
        connection: IntegrationConnection,
        *,
        tool_name: str | None,
        keep_connection_on_failure: bool,
    ) -> IntegrationConnectionResponse:
        credential_uuid: str | None = None
        issued: IssuedConnectionKey | None = None
        tool_uuid: str | None = None
        succeeded = False
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
                actor.caller,
                connection.id,
                fallcha_credential_uuid=credential_uuid,
                exclusive=True,
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
                    name=tool_name or provider.title,
                    description=provider.description or None,
                    icon=_icon(provider),
                    url=self.mcp_url(provider.id),
                    credential_uuid=credential_uuid,
                ),
            )
            succeeded = True
        finally:
            # ``finally`` (not ``except Exception``) so a cancelled request is
            # rolled back too.
            if not succeeded:
                logger.warning(
                    f"Activating {provider.id} for org {actor.organization_id} "
                    f"failed; rolling back connection {connection.id}"
                )
                await self._compensate(
                    actor,
                    connection.id,
                    credential_uuid,
                    tool_uuid,
                    revoke_key_id=(
                        issued.id
                        if keep_connection_on_failure and issued is not None
                        else None
                    ),
                    revoke_connection=not keep_connection_on_failure,
                )

        logger.info(
            f"Activated {provider.id} for org {actor.organization_id}: "
            f"connection {connection.id}, tool {tool_uuid}"
        )
        return IntegrationConnectionResponse(
            **connection.model_dump(),
            credential_uuid=credential_uuid,
            tool_uuids=[tool_uuid] if tool_uuid else [],
        )

    # -- OAuth2 ----------------------------------------------------------

    async def list_provider_apps(self, actor: Actor) -> ProviderAppListResponse:
        return await self._tools.list_provider_apps(actor.caller)

    async def create_provider_app(
        self, actor: Actor, request: CreateProviderAppRequest
    ) -> ProviderAppResponse:
        return await self._tools.create_provider_app(actor.caller, request)

    async def delete_provider_app(self, actor: Actor, app_id: uuid.UUID) -> None:
        await self._tools.delete_provider_app(actor.caller, app_id)

    async def start_oauth(
        self, actor: Actor, request: StartOAuthRequest
    ) -> StartedOAuth:
        """``browser_nonce`` is for the starting user's browser only: return
        it to that user and never log it."""
        return await self._tools.start_oauth(actor.caller, request)

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
            # Deleted credentials too, so no tool that used one stays active.
            for c in await self._resources.list_linked_credentials(
                actor.organization_id, include_deleted=True
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
        self,
        actor: Actor,
        connection_id: uuid.UUID,
        credential_uuid: str | None,
        tool_uuid: str | None,
        *,
        revoke_key_id: uuid.UUID | None,
        revoke_connection: bool,
    ) -> None:
        """Best-effort rollback; failures are logged, never raised, so the
        caller sees the original error."""
        if tool_uuid is not None:
            try:
                await self._resources.archive_tool(
                    organization_id=actor.organization_id, tool_uuid=tool_uuid
                )
            except Exception as exc:  # noqa: BLE001 - rollback is best-effort
                logger.error(
                    f"Rollback could not archive tool {tool_uuid} for org "
                    f"{actor.organization_id}: {type(exc).__name__}"
                )
        if revoke_connection:
            try:
                await self._tools.revoke_connection(actor.caller, connection_id)
            except Exception as exc:  # noqa: BLE001 - rollback is best-effort
                logger.error(
                    f"Rollback could not revoke connection {connection_id} for "
                    f"org {actor.organization_id}: {type(exc).__name__}"
                )
        elif revoke_key_id is not None:
            try:
                await self._tools.revoke_key(actor.caller, connection_id, revoke_key_id)
            except Exception as exc:  # noqa: BLE001 - rollback is best-effort
                logger.error(
                    f"Rollback could not revoke key {revoke_key_id} of connection "
                    f"{connection_id} for org {actor.organization_id}: "
                    f"{type(exc).__name__}"
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
