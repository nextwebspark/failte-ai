"""Per-provider MCP servers, mounted under ``/mcp/{provider_id}``.

Each registered provider gets its own FastMCP server guarded by a
:class:`ConnectionKeyVerifier` bound to that provider. Servers run in
stateless streamable-HTTP mode, so any replica can serve any request.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.http import StarletteWithLifespan
from starlette._utils import get_route_path
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from fallcha_tools.core.auth import (
    CLAIM_CONNECTION_ID,
    CLAIM_ORG_ID,
    CLAIM_PROVIDER,
    ConnectionKeyVerifier,
    KeyLookup,
)
from fallcha_tools.core.context import ContextLoader
from fallcha_tools.core.errors import ToolsError
from fallcha_tools.core.provider import (
    ConnectionContext,
    ConnectionContextFactory,
    ProviderRegistry,
)


@dataclass(frozen=True, slots=True)
class ConnectionResolver:
    """Builds a :class:`ConnectionContext` for the key on the current request."""

    loader: ContextLoader

    def for_provider(self, provider_id: str) -> ConnectionContextFactory:
        async def resolve() -> ConnectionContext:
            return await self.resolve(provider_id)

        return resolve

    async def resolve(self, provider_id: str) -> ConnectionContext:
        token = get_access_token()
        claims = (token.claims or {}) if token is not None else {}
        if claims.get(CLAIM_PROVIDER) != provider_id:
            raise ToolError("request is not authenticated for this provider")
        org_id = int(claims[CLAIM_ORG_ID])
        connection_id = uuid.UUID(str(claims[CLAIM_CONNECTION_ID]))
        try:
            return await self.loader.load(org_id, connection_id, provider_id)
        except ToolsError as exc:
            raise ToolError(str(exc)) from exc


class McpMounts:
    """One FastMCP server + Starlette app per provider, plus their lifespans."""

    def __init__(
        self,
        registry: ProviderRegistry,
        resolver: ConnectionResolver,
        lookup: KeyLookup,
    ) -> None:
        self.servers: dict[str, FastMCP[Any]] = {}
        self.apps: dict[str, StarletteWithLifespan] = {}
        for provider in registry:
            server: FastMCP[Any] = FastMCP(
                name=provider.id,
                auth=ConnectionKeyVerifier(provider.id, lookup),
                mask_error_details=True,
            )
            provider.register_tools(server, resolver.for_provider(provider.id))
            self.servers[provider.id] = server
            # host_origin_protection off: the service is internal-only and
            # every request needs a bearer key, so DNS rebinding buys nothing.
            self.apps[provider.id] = server.http_app(
                path="/",
                stateless_http=True,
                json_response=True,
                host_origin_protection=False,
            )

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """Run every MCP app's lifespan (session managers) for the app's life."""
        async with AsyncExitStack() as stack:
            for app in self.apps.values():
                await stack.enter_async_context(app.router.lifespan_context(app))
            yield

    async def tool_summaries(
        self, provider_id: str
    ) -> list[tuple[str, str, str | None]]:
        """(name, description for the agent, short human title) per tool."""
        server = self.servers.get(provider_id)
        if server is None:
            return []
        tools = await server.list_tools(run_middleware=False)
        return [(tool.name, tool.description or "", tool.title) for tool in tools]


class McpGateway:
    """ASGI app mounted at ``/mcp`` that dispatches on the provider segment.

    A plain ``Mount("/mcp/<id>")`` would answer ``/mcp/<id>`` (no trailing
    slash) with a 307; MCP clients are configured with the bare URL, so this
    routes both forms straight to the provider's app.
    """

    def __init__(self, apps: Mapping[str, StarletteWithLifespan]) -> None:
        self._apps = apps

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        provider_id, _, rest = get_route_path(scope).lstrip("/").partition("/")
        app = self._apps.get(provider_id)
        if app is None:
            response = JSONResponse({"detail": "unknown provider"}, status_code=404)
            await response(scope, receive, send)
            return
        root_path = f"{scope.get('root_path', '')}/{provider_id}"
        child: dict[str, Any] = {**scope, "root_path": root_path}
        if not rest:
            child["path"] = root_path + "/"
        await app(child, receive, send)
