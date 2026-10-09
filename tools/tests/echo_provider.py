"""Test-only provider: echoes input and reports which connection it ran as."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter
from fastmcp import FastMCP
from pydantic import BaseModel, JsonValue

from fallcha_tools.core.models import AuthMode
from fallcha_tools.core.provider import (
    ConnectionContext,
    ConnectionContextFactory,
    ConnectionTestResult,
    RestContextDependency,
)


@dataclass(frozen=True)
class EchoProvider:
    id: str = "echo"
    title: str = "Echo"
    description: str = "Echoes text back."
    icon: str = "echo"
    auth_modes: frozenset[AuthMode] = field(
        default_factory=lambda: frozenset({AuthMode.API_KEY})
    )
    scopes: tuple[str, ...] = ()
    config_model: type[BaseModel] | None = None

    def validate_secret(
        self, auth_mode: AuthMode, secret: Mapping[str, JsonValue]
    ) -> None:
        del auth_mode, secret

    def rest_router(self, ctx_dependency: RestContextDependency) -> APIRouter | None:
        del ctx_dependency
        return None

    def register_tools(
        self, mcp: FastMCP[Any], ctx_factory: ConnectionContextFactory
    ) -> None:
        @mcp.tool
        async def echo(text: str) -> str:
            """Echo the text back, tagged with the calling org."""
            ctx = await ctx_factory()
            return f"{text} (org={ctx.org_id}, key={ctx.secret.get('api_key')})"

        @mcp.tool
        async def whoami() -> dict[str, str | int]:
            """Report the connection this call runs as."""
            ctx = await ctx_factory()
            return {
                "org_id": ctx.org_id,
                "connection_id": str(ctx.connection_id),
                "provider": ctx.provider,
            }

    async def test_connection(self, ctx: ConnectionContext) -> ConnectionTestResult:
        if ctx.secret.get("api_key") == "raise":
            raise RuntimeError(f"provider exploded with {ctx.secret['api_key']}-leak")
        if ctx.secret.get("api_key") == "good":
            return ConnectionTestResult(ok=True, account_label="echo-account")
        return ConnectionTestResult(ok=False, message="bad api key")
