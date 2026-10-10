"""The Google Sheets provider: wiring between the core and the service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import APIRouter
from fastmcp import FastMCP
from pydantic import BaseModel, JsonValue, ValidationError

from fallcha_tools.core.models import AuthMode
from fallcha_tools.core.provider import (
    ConnectionContext,
    ConnectionContextFactory,
    ConnectionTestResult,
    OAuthSpec,
    RestContextDependency,
)
from fallcha_tools.providers.google_common.connection import (
    GOOGLE_AUTH_MODES,
    GoogleAuthFactory,
    google_oauth_spec,
    validate_google_secret,
)
from fallcha_tools.providers.google_common.credentials import (
    Clock,
    SignerCache,
    TokenCache,
    utc_now,
)
from fallcha_tools.providers.google_common.errors import (
    GoogleApiError,
    GoogleToolError,
    NotConfiguredError,
)
from fallcha_tools.providers.google_common.http import DEFAULT_TIMEOUT
from fallcha_tools.providers.google_common.scopes import SHEETS_SCOPE
from fallcha_tools.providers.google_sheets.client import SheetsClient
from fallcha_tools.providers.google_sheets.service import (
    DEFAULT_DEADLINE_SECONDS,
    SheetsService,
)
from fallcha_tools.providers.google_sheets.settings import SheetsConfig
from fallcha_tools.providers.google_sheets.tools import register_sheets_tools

# Read and write (append_row needs it); Google has no narrower scope that
# allows appending. No optional scopes. ``openid email`` only labels the
# connection. A new OAuth connection has no spreadsheet until one is set.
SHEETS_OAUTH = google_oauth_spec(scopes=(SHEETS_SCOPE,))


@dataclass(frozen=True)
class GoogleSheetsProvider:
    """Find, read and append rows in one Google Sheet per connection."""

    token_cache: TokenCache = field(default_factory=TokenCache)
    signer_cache: SignerCache = field(default_factory=SignerCache)
    clock: Clock = utc_now
    request_timeout: httpx.Timeout = field(default_factory=lambda: DEFAULT_TIMEOUT)
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS

    @property
    def id(self) -> str:
        return "google-sheets"

    @property
    def title(self) -> str:
        return "Google Sheets"

    @property
    def description(self) -> str:
        return (
            "Look up rows in a Google Sheet by any column, read a row, and add "
            "new rows (for example leads or messages) by column name."
        )

    @property
    def icon(self) -> str:
        return "sheet"

    @property
    def auth_modes(self) -> frozenset[AuthMode]:
        return GOOGLE_AUTH_MODES

    @property
    def scopes(self) -> tuple[str, ...]:
        return (SHEETS_SCOPE,)

    @property
    def config_model(self) -> type[BaseModel]:
        return SheetsConfig

    @property
    def oauth(self) -> OAuthSpec:
        return SHEETS_OAUTH

    def validate_secret(
        self, auth_mode: AuthMode, secret: Mapping[str, JsonValue]
    ) -> None:
        validate_google_secret(auth_mode, secret)

    def register_tools(
        self, mcp: FastMCP[Any], ctx_factory: ConnectionContextFactory
    ) -> None:
        register_sheets_tools(mcp, ctx_factory, self.service_for)

    def rest_router(self, ctx_dependency: RestContextDependency) -> APIRouter | None:
        del ctx_dependency
        return None

    async def test_connection(self, ctx: ConnectionContext) -> ConnectionTestResult:
        try:
            service = self.service_for(ctx)
        except GoogleToolError as exc:
            return ConnectionTestResult(ok=False, message=str(exc))
        try:
            info, missing = await service.describe()
        except GoogleApiError as exc:
            hint = service.client.account_hint
            if (
                exc.access_problem
                and hint
                and ctx.auth_mode == AuthMode.SERVICE_ACCOUNT
            ):
                # Admin-only: names the account to share the sheet with.
                return ConnectionTestResult(
                    ok=False,
                    message=f"{exc.access_problem}; share it with {hint} "
                    "(Editor, so rows can be added)",
                )
            return ConnectionTestResult(ok=False, message=str(exc))
        except GoogleToolError as exc:
            return ConnectionTestResult(ok=False, message=str(exc))
        if missing:
            return ConnectionTestResult(
                ok=False,
                message=f"the spreadsheet {info.title!r} has no tab named "
                + ", ".join(repr(t) for t in missing),
            )
        return ConnectionTestResult(
            ok=True,
            message=f"Connected to the spreadsheet {info.title!r} "
            f"({len(info.tabs)} tab{'s' if len(info.tabs) != 1 else ''})",
            account_label=service.client.account_hint,
        )

    def service_for(self, ctx: ConnectionContext) -> SheetsService:
        try:
            config = SheetsConfig.model_validate(dict(ctx.config))
        except ValidationError:
            raise NotConfiguredError(
                "the spreadsheet for this connection is not set up yet"
            ) from None
        auth = GoogleAuthFactory(
            product=self.title,
            token_cache=self.token_cache,
            signer_cache=self.signer_cache,
            clock=self.clock,
            request_timeout=self.request_timeout,
        ).for_context(ctx)
        client = SheetsClient(
            http=ctx.http,
            credentials=auth.credentials,
            account_hint=auth.account_hint,
            timeout=self.request_timeout,
        )
        return SheetsService(
            client=client, config=config, deadline_seconds=self.deadline_seconds
        )
