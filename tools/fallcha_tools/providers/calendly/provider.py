"""The Calendly provider: wiring between the core and the service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter
from fastmcp import FastMCP
from pydantic import BaseModel, JsonValue, ValidationError

from fallcha_tools.core.errors import InvalidRequestError, describe_validation_error
from fallcha_tools.core.models import AuthMode
from fallcha_tools.core.provider import (
    BookingListFailed,
    ConfigChoices,
    ConfigChoicesFailed,
    ConnectionContext,
    ConnectionContextFactory,
    ConnectionTestResult,
    OAuthSpec,
    RestContextDependency,
)
from fallcha_tools.providers.calendly.client import (
    DEFAULT_TIMEOUT,
    SCOPES,
    CalendlyApiError,
    CalendlyClient,
    CalendlyError,
    OAuthToken,
    StaticToken,
    TokenSource,
)
from fallcha_tools.providers.calendly.schemas import Booking
from fallcha_tools.providers.calendly.service import (
    DEFAULT_DEADLINE_SECONDS,
    AccountCache,
    CalendlyService,
    Clock,
    account_from,
)
from fallcha_tools.providers.calendly.settings import CalendlyConfig, CalendlyToken
from fallcha_tools.providers.calendly.tools import register_calendly_tools

CALENDLY_AUTHORIZE_URL = "https://auth.calendly.com/oauth/authorize"
CALENDLY_TOKEN_URL = "https://auth.calendly.com/oauth/token"
TOKEN_KEY = "token"

# Bring-your-own OAuth app (registered at developer.calendly.com). Calendly's
# revoke endpoint needs the client's credentials, which the core's erasure
# does not send, so no revocation URL: erasing a workspace deletes the grant
# here, and the owner can disconnect the app in Calendly.
CALENDLY_OAUTH = OAuthSpec(
    display_name="Calendly",
    authorize_url=CALENDLY_AUTHORIZE_URL,
    token_url=CALENDLY_TOKEN_URL,
    scopes=SCOPES,
)

TOKEN_REJECTED = (
    "Calendly didn't accept this token. Copy it again from Calendly "
    "(Integrations, then API and webhooks) and paste the whole token."
)
TOKEN_MISSING_SCOPES = (
    "This token can't read your Calendly account. Create a new personal access "
    f"token and allow these permissions: {', '.join(SCOPES)}."
)
CALENDLY_UNREACHABLE = "Couldn't reach Calendly to check the token. Please try again."


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class CalendlyProvider:
    """Offer free times from a Calendly event type and book callers into it."""

    clock: Clock = _now
    request_timeout: httpx.Timeout = field(default_factory=lambda: DEFAULT_TIMEOUT)
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS
    accounts: AccountCache = field(default_factory=AccountCache)

    @property
    def id(self) -> str:
        return "calendly"

    @property
    def title(self) -> str:
        return "Calendly"

    @property
    def description(self) -> str:
        return (
            "Offer free times from one of your Calendly events and book callers "
            "into it (Calendly emails them the details)."
        )

    @property
    def icon(self) -> str:
        return "calendar"

    @property
    def share_hint(self) -> str | None:
        return None

    @property
    def auth_family(self) -> str | None:
        return None

    @property
    def auth_modes(self) -> frozenset[AuthMode]:
        return frozenset({AuthMode.API_KEY, AuthMode.OAUTH2})

    @property
    def scopes(self) -> tuple[str, ...]:
        return SCOPES

    @property
    def config_model(self) -> type[BaseModel]:
        return CalendlyConfig

    @property
    def oauth(self) -> OAuthSpec:
        return CALENDLY_OAUTH

    def validate_secret(
        self, auth_mode: AuthMode, secret: Mapping[str, JsonValue]
    ) -> None:
        if auth_mode != AuthMode.API_KEY:
            return
        try:
            CalendlyToken.model_validate(dict(secret))
        except ValidationError as exc:
            raise InvalidRequestError(
                f"invalid Calendly token: {describe_validation_error(exc)}"
            ) from None

    async def check_new_secret(
        self,
        http: httpx.AsyncClient,
        auth_mode: AuthMode,
        secret: Mapping[str, JsonValue],
    ) -> str | None:
        """``GET /users/me`` with a pasted token, before it is saved."""
        if auth_mode != AuthMode.API_KEY:
            return None
        token = CalendlyToken.model_validate(dict(secret)).token
        client = CalendlyClient(
            http=http, tokens=StaticToken(token), timeout=self.request_timeout
        )
        try:
            account = account_from(await client.get("/users/me"))
        except CalendlyApiError as exc:
            if exc.status == 401:
                raise InvalidRequestError(TOKEN_REJECTED) from None
            if exc.status == 403:
                raise InvalidRequestError(TOKEN_MISSING_SCOPES) from None
            raise InvalidRequestError(CALENDLY_UNREACHABLE) from None
        return account.email or account.name

    def register_tools(
        self, mcp: FastMCP[Any], ctx_factory: ConnectionContextFactory
    ) -> None:
        register_calendly_tools(mcp, ctx_factory, self.service_for)

    def rest_router(self, ctx_dependency: RestContextDependency) -> APIRouter | None:
        del ctx_dependency
        return None

    async def test_connection(self, ctx: ConnectionContext) -> ConnectionTestResult:
        try:
            message, label = await self.service_for(ctx).check_access()
        except CalendlyError as exc:
            return ConnectionTestResult(ok=False, message=str(exc))
        except TimeoutError:
            return ConnectionTestResult(
                ok=False, message="Calendly did not respond in time"
            )
        return ConnectionTestResult(ok=True, message=message, account_label=label)

    async def list_bookings(
        self, ctx: ConnectionContext, start: datetime, end: datetime
    ) -> Sequence[Booking]:
        try:
            return await self.service_for(ctx).list_bookings(start, end)
        except CalendlyError as exc:
            raise BookingListFailed(str(exc)) from None

    async def config_choices(self, ctx: ConnectionContext) -> ConfigChoices:
        try:
            return await self.service_for(ctx).choices()
        except CalendlyError as exc:
            raise ConfigChoicesFailed(str(exc)) from None
        except TimeoutError:
            raise ConfigChoicesFailed("Calendly did not respond in time") from None

    def service_for(self, ctx: ConnectionContext) -> CalendlyService:
        try:
            config = CalendlyConfig.model_validate(dict(ctx.config))
        except ValidationError:
            raise CalendlyError(
                "the Calendly settings for this connection are missing or invalid"
            ) from None
        return CalendlyService(
            client=CalendlyClient(
                http=ctx.http, tokens=self._tokens(ctx), timeout=self.request_timeout
            ),
            config=config,
            connection_id=ctx.connection_id,
            clock=self.clock,
            accounts=self.accounts,
            deadline_seconds=self.deadline_seconds,
            contact_phone=ctx.contact_phone,
        )

    @staticmethod
    def _tokens(ctx: ConnectionContext) -> TokenSource:
        if ctx.auth_mode == AuthMode.OAUTH2:
            if ctx.oauth is None:
                raise CalendlyError("this Calendly connection needs reconnecting")
            return OAuthToken(ctx.oauth)
        token = ctx.secret.get(TOKEN_KEY)
        if not isinstance(token, str) or not token:
            raise CalendlyError("this Calendly connection has no token")
        return StaticToken(token)
