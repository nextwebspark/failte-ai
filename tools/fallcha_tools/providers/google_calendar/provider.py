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
from fallcha_tools.core.errors import InvalidRequestError, describe_validation_error
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
    SHEETS_READONLY_SCOPE,
    GoogleClient,
)
from fallcha_tools.providers.google_calendar.credentials import (
    GOOGLE_TOKEN_URL,
    Clock,
    GoogleCredentialsSource,
    OAuthCredentials,
    ServiceAccountCredentials,
    SignerCache,
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

BOOKING_ID_LABEL = "fallcha-tools/google-calendar/booking-event-id/v1"

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

# Least privilege: event read/write plus read-only calendar access (free/busy
# and the calendar's name); never full ``calendar``. Sheets is opt-in at
# connect time, read-only, and only needed for order lookup. ``openid email``
# only labels the connection with the account's address.
GOOGLE_OAUTH = OAuthSpec(
    display_name="Google",
    authorize_url=GOOGLE_AUTHORIZE_URL,
    token_url=GOOGLE_TOKEN_URL,
    userinfo_url=GOOGLE_USERINFO_URL,
    scopes=(CALENDAR_EVENTS_SCOPE, CALENDAR_READONLY_SCOPE),
    optional_scopes=(SHEETS_READONLY_SCOPE,),
    identity_scopes=("openid", "email"),
    authorize_params={
        "access_type": "offline",  # we need a refresh token
        "prompt": "consent",  # ... every time, even on a reconnect
        "include_granted_scopes": "true",
    },
    default_config={"calendar_id": "primary"},
)


def booking_id_key_from(internal_secret: str) -> bytes:
    """The booking-id HMAC key, derived from the service's internal secret."""
    return derive_key(internal_secret, BOOKING_ID_LABEL)


@dataclass(frozen=True)
class GoogleCalendarProvider:
    """Check availability, book, cancel, and look up orders in a Google Sheet.

    ``booking_id_key`` keys the HMAC behind booking event ids; it must be the
    same on every replica (see :func:`booking_id_key_from`).
    """

    booking_id_key: bytes = field(repr=False)
    token_cache: TokenCache = field(default_factory=TokenCache)
    signer_cache: SignerCache = field(default_factory=SignerCache)
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
        return frozenset({AuthMode.SERVICE_ACCOUNT, AuthMode.OAUTH2})

    @property
    def scopes(self) -> tuple[str, ...]:
        return (CALENDAR_SCOPE, SHEETS_READONLY_SCOPE)

    @property
    def config_model(self) -> type[BaseModel]:
        return CalendarConfig

    @property
    def oauth(self) -> OAuthSpec:
        return GOOGLE_OAUTH

    def validate_secret(
        self, auth_mode: AuthMode, secret: Mapping[str, JsonValue]
    ) -> None:
        if auth_mode != AuthMode.SERVICE_ACCOUNT:
            return
        try:
            ServiceAccountKey.model_validate(dict(secret))
        except ValidationError as exc:
            raise InvalidRequestError(
                f"invalid service-account key: {describe_validation_error(exc)}"
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
            booking_id_key=self.booking_id_key,
            deadline_seconds=self.deadline_seconds,
        )

    def _client(self, ctx: ConnectionContext) -> GoogleClient:
        credentials: GoogleCredentialsSource
        if ctx.auth_mode == AuthMode.OAUTH2:
            if ctx.oauth is None:
                raise NotConfiguredError("this Google connection is not usable")
            credentials = OAuthCredentials(
                connection_id=ctx.connection_id,
                tokens=ctx.oauth,
                cache=self.token_cache,
                scopes_granted=ctx.scopes_granted,
            )
            return GoogleClient(
                http=ctx.http,
                credentials=credentials,
                account_hint=ctx.account_label,
                timeout=self.request_timeout,
            )
        if ctx.auth_mode != AuthMode.SERVICE_ACCOUNT:
            raise NotConfiguredError(
                f"{ctx.auth_mode} connections are not supported by Google Calendar"
            )
        try:
            signer = self.signer_cache.get(ctx.connection_id, ctx.secret)
        except ValidationError:
            raise NotConfiguredError(
                "the service-account key for this connection is invalid"
            ) from None
        credentials = ServiceAccountCredentials(
            connection_id=ctx.connection_id,
            signer=signer,
            http=ctx.http,
            cache=self.token_cache,
            timeout=self.request_timeout,
            clock=self.clock,
        )
        return GoogleClient(
            http=ctx.http,
            credentials=credentials,
            account_hint=signer.client_email,
            timeout=self.request_timeout,
        )
