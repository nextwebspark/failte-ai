"""The Google Calendar provider: wiring between the core and the service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import APIRouter
from fastmcp import FastMCP
from pydantic import BaseModel, JsonValue, ValidationError

from fallcha_tools.core.errors import InvalidRequestError
from fallcha_tools.core.models import AuthMode
from fallcha_tools.core.provider import (
    ConnectionContext,
    ConnectionContextFactory,
    ConnectionTestResult,
    RestContextDependency,
)
from fallcha_tools.providers.google_calendar.client import (
    CALENDAR_SCOPE,
    DEFAULT_TIMEOUT,
    SHEETS_READONLY_SCOPE,
    GoogleClient,
)
from fallcha_tools.providers.google_calendar.credentials import (
    Clock,
    ServiceAccountCredentials,
    TokenCache,
    utc_now,
)
from fallcha_tools.providers.google_calendar.errors import (
    CalendarToolError,
    NotConfiguredError,
)
from fallcha_tools.providers.google_calendar.orders import OrdersCache
from fallcha_tools.providers.google_calendar.rest import build_rest_router
from fallcha_tools.providers.google_calendar.service import (
    DEFAULT_DEADLINE_SECONDS,
    CalendarService,
)
from fallcha_tools.providers.google_calendar.settings import (
    CalendarConfig,
    ServiceAccountKey,
)
from fallcha_tools.providers.google_calendar.tools import register_calendar_tools


def _problems(exc: ValidationError) -> str:
    # Locations and reasons only: inputs may be secret.
    return "; ".join(
        f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
        for err in exc.errors(include_input=False, include_url=False)
    )


@dataclass(frozen=True)
class GoogleCalendarProvider:
    """Check availability, book, cancel, and look up orders in a Google Sheet."""

    token_cache: TokenCache = field(default_factory=TokenCache)
    orders_cache: OrdersCache = field(default_factory=OrdersCache)
    clock: Clock = utc_now
    request_timeout: httpx.Timeout = field(default_factory=lambda: DEFAULT_TIMEOUT)
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS

    @property
    def id(self) -> str:
        return "google-calendar"

    @property
    def title(self) -> str:
        return "Google Calendar"

    @property
    def description(self) -> str:
        return (
            "Offer free appointment slots, book and cancel appointments on a "
            "Google Calendar, and look up orders in a Google Sheet (read-only)."
        )

    @property
    def icon(self) -> str:
        return "calendar"

    @property
    def auth_modes(self) -> frozenset[AuthMode]:
        return frozenset({AuthMode.SERVICE_ACCOUNT})

    @property
    def scopes(self) -> tuple[str, ...]:
        return (CALENDAR_SCOPE, SHEETS_READONLY_SCOPE)

    @property
    def config_model(self) -> type[BaseModel]:
        return CalendarConfig

    def validate_secret(
        self, auth_mode: AuthMode, secret: Mapping[str, JsonValue]
    ) -> None:
        if auth_mode != AuthMode.SERVICE_ACCOUNT:
            return
        try:
            ServiceAccountKey.model_validate(dict(secret))
        except ValidationError as exc:
            raise InvalidRequestError(
                f"invalid service-account key: {_problems(exc)}"
            ) from None

    def register_tools(
        self, mcp: FastMCP[Any], ctx_factory: ConnectionContextFactory
    ) -> None:
        register_calendar_tools(mcp, ctx_factory, self.service_for)

    def rest_router(self, ctx_dependency: RestContextDependency) -> APIRouter:
        return build_rest_router(ctx_dependency, self.service_for)

    async def test_connection(self, ctx: ConnectionContext) -> ConnectionTestResult:
        try:
            service = self.service_for(ctx)
            message = await service.check_access()
        except CalendarToolError as exc:
            return ConnectionTestResult(ok=False, message=str(exc))
        return ConnectionTestResult(
            ok=True, message=message, account_label=service.client.account_hint
        )

    def service_for(self, ctx: ConnectionContext) -> CalendarService:
        try:
            config = CalendarConfig.model_validate(dict(ctx.config))
        except ValidationError:
            raise NotConfiguredError(
                "the calendar settings for this connection are missing or invalid"
            ) from None
        return CalendarService(
            client=self._client(ctx),
            config=config,
            connection_id=ctx.connection_id,
            clock=self.clock,
            orders_cache=self.orders_cache,
            deadline_seconds=self.deadline_seconds,
        )

    def _client(self, ctx: ConnectionContext) -> GoogleClient:
        if ctx.auth_mode != AuthMode.SERVICE_ACCOUNT:
            raise NotConfiguredError(
                f"{ctx.auth_mode} connections are not supported by Google Calendar yet"
            )
        try:
            key = ServiceAccountKey.model_validate(dict(ctx.secret))
        except ValidationError:
            raise NotConfiguredError(
                "the service-account key for this connection is invalid"
            ) from None
        credentials = ServiceAccountCredentials(
            connection_id=ctx.connection_id,
            key=key,
            http=ctx.http,
            cache=self.token_cache,
            timeout=self.request_timeout,
            clock=self.clock,
        )
        return GoogleClient(
            http=ctx.http,
            credentials=credentials,
            account_hint=key.client_email,
            timeout=self.request_timeout,
        )
