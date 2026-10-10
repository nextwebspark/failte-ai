"""The Google Calendar provider: wiring between the core and the service."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import APIRouter
from fastmcp import FastMCP
from pydantic import BaseModel, JsonValue, ValidationError

from fallcha_tools.core.crypto import derive_key
from fallcha_tools.core.models import AuthMode
from fallcha_tools.core.provider import (
    ConnectionContext,
    ConnectionContextFactory,
    ConnectionTestResult,
    OAuthSpec,
    RestContextDependency,
)
from fallcha_tools.providers.google_calendar.client import (
    CALENDAR_EVENTS_SCOPE,
    CALENDAR_READONLY_SCOPE,
    CALENDAR_SCOPE,
    DEFAULT_TIMEOUT,
    GoogleClient,
)
from fallcha_tools.providers.google_calendar.errors import (
    CalendarToolError,
    NotConfiguredError,
)
from fallcha_tools.providers.google_calendar.rest import build_rest_router
from fallcha_tools.providers.google_calendar.service import (
    DEFAULT_DEADLINE_SECONDS,
    CalendarService,
)
from fallcha_tools.providers.google_calendar.settings import CalendarConfig
from fallcha_tools.providers.google_calendar.tools import register_calendar_tools
from fallcha_tools.providers.google_common.connection import (
    GOOGLE_AUTH_MODES,
    GOOGLE_FAMILY,
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
from fallcha_tools.providers.google_common.scopes import (
    GOOGLE_AUTHORIZE_URL,
    GOOGLE_USERINFO_URL,
)

__all__ = [
    "GOOGLE_AUTHORIZE_URL",
    "GOOGLE_OAUTH",
    "GOOGLE_USERINFO_URL",
    "GoogleCalendarProvider",
    "booking_id_key_from",
]

BOOKING_ID_LABEL = "fallcha-tools/google-calendar/booking-event-id/v1"

# Least privilege: event read/write plus read-only calendar access (free/busy
# and the calendar's name); never full ``calendar``, and no optional scopes
# (order lookup is a Google Sheets tool). ``openid email`` only labels the
# connection with the account's address.
GOOGLE_OAUTH = google_oauth_spec(
    scopes=(CALENDAR_EVENTS_SCOPE, CALENDAR_READONLY_SCOPE),
    default_config={"calendar_id": "primary"},
)


def booking_id_key_from(internal_secret: str) -> bytes:
    """The booking-id HMAC key, derived from the service's internal secret."""
    return derive_key(internal_secret, BOOKING_ID_LABEL)


@dataclass(frozen=True)
class GoogleCalendarProvider:
    """Check availability, book and cancel appointments.

    ``booking_id_key`` keys the HMAC behind booking event ids; it must be the
    same on every replica (see :func:`booking_id_key_from`).
    """

    booking_id_key: bytes = field(repr=False)
    token_cache: TokenCache = field(default_factory=TokenCache)
    signer_cache: SignerCache = field(default_factory=SignerCache)
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
            "Offer free appointment slots, and book and cancel appointments, "
            "on a Google Calendar."
        )

    @property
    def icon(self) -> str:
        return "calendar"

    @property
    def auth_family(self) -> str:
        return GOOGLE_FAMILY

    @property
    def auth_modes(self) -> frozenset[AuthMode]:
        return GOOGLE_AUTH_MODES

    @property
    def scopes(self) -> tuple[str, ...]:
        return (CALENDAR_SCOPE,)

    @property
    def config_model(self) -> type[BaseModel]:
        return CalendarConfig

    @property
    def oauth(self) -> OAuthSpec:
        return GOOGLE_OAUTH

    def validate_secret(
        self, auth_mode: AuthMode, secret: Mapping[str, JsonValue]
    ) -> None:
        validate_google_secret(auth_mode, secret)

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
            booking_id_key=self.booking_id_key,
            deadline_seconds=self.deadline_seconds,
        )

    def _client(self, ctx: ConnectionContext) -> GoogleClient:
        auth = GoogleAuthFactory(
            product=self.title,
            token_cache=self.token_cache,
            signer_cache=self.signer_cache,
            clock=self.clock,
            request_timeout=self.request_timeout,
        ).for_context(ctx)
        return GoogleClient(
            http=ctx.http,
            credentials=auth.credentials,
            account_hint=auth.account_hint,
            timeout=self.request_timeout,
        )
