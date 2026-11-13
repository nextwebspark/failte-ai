"""The Outlook Calendar provider: Google Calendar's booking service on
Microsoft Graph (see :mod:`fallcha_tools.providers.outlook_calendar.graph`)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter
from fastmcp import FastMCP
from pydantic import BaseModel, Field, JsonValue, ValidationError

from fallcha_tools.core.models import AuthMode
from fallcha_tools.core.provider import (
    BookingListFailed,
    ConnectionContext,
    ConnectionContextFactory,
    ConnectionTestResult,
    OAuthSpec,
    RestContextDependency,
)
from fallcha_tools.providers.google_calendar.errors import (
    CalendarToolError,
    NotConfiguredError,
)
from fallcha_tools.providers.google_calendar.schemas import Booking
from fallcha_tools.providers.google_calendar.service import (
    DEFAULT_DEADLINE_SECONDS,
    CalendarService,
)
from fallcha_tools.providers.google_calendar.settings import CalendarConfig
from fallcha_tools.providers.google_calendar.tools import register_calendar_tools
from fallcha_tools.providers.google_common.credentials import (
    Clock,
    TokenCache,
    utc_now,
)
from fallcha_tools.providers.google_common.http import DEFAULT_TIMEOUT
from fallcha_tools.providers.outlook_calendar.auth import (
    CALENDARS_SCOPE,
    MICROSOFT_FAMILY,
    MicrosoftCredentials,
    microsoft_oauth_spec,
)
from fallcha_tools.providers.outlook_calendar.graph import (
    PRIMARY,
    GraphCalendarClient,
)

__all__ = ["OutlookCalendarConfig", "OutlookCalendarProvider"]


class OutlookCalendarConfig(CalendarConfig):
    """Google Calendar's booking rules; only the calendar is named the
    Outlook way."""

    calendar_id: str = Field(
        default=PRIMARY,
        min_length=1,
        max_length=1024,
        description="Outlook calendar: primary (the account's default "
        "calendar) or a calendar's Microsoft Graph id.",
    )


@dataclass(frozen=True)
class OutlookCalendarProvider:
    """Check availability, book, find, move and cancel appointments in an
    Outlook calendar, with the same booking rules as Google Calendar.

    ``booking_id_key`` keys the HMAC behind booking ids (the same on every
    replica); ``tenant`` is the Microsoft sign-in audience ("common")."""

    booking_id_key: bytes = field(repr=False)
    tenant: str = "common"
    token_cache: TokenCache = field(default_factory=TokenCache)
    clock: Clock = utc_now
    request_timeout: httpx.Timeout = field(default_factory=lambda: DEFAULT_TIMEOUT)
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS

    @property
    def id(self) -> str:
        return "outlook-calendar"

    @property
    def title(self) -> str:
        return "Outlook Calendar"

    @property
    def description(self) -> str:
        return (
            "Offer free appointment slots, and book, find, move and cancel "
            "appointments, on an Outlook (Microsoft 365) calendar."
        )

    @property
    def icon(self) -> str:
        return "calendar"

    @property
    def share_hint(self) -> str | None:
        return None

    @property
    def auth_family(self) -> str:
        return MICROSOFT_FAMILY

    @property
    def auth_modes(self) -> frozenset[AuthMode]:
        return frozenset({AuthMode.OAUTH2})

    @property
    def scopes(self) -> tuple[str, ...]:
        return (CALENDARS_SCOPE,)

    @property
    def config_model(self) -> type[BaseModel]:
        return OutlookCalendarConfig

    @property
    def oauth(self) -> OAuthSpec:
        return microsoft_oauth_spec(
            self.tenant, default_config={"calendar_id": PRIMARY}
        )

    def validate_secret(
        self, auth_mode: AuthMode, secret: Mapping[str, JsonValue]
    ) -> None:
        """OAuth secrets never reach here (the callback stores them)."""
        del auth_mode, secret

    def register_tools(
        self, mcp: FastMCP[Any], ctx_factory: ConnectionContextFactory
    ) -> None:
        register_calendar_tools(mcp, ctx_factory, self.service_for)

    def rest_router(self, ctx_dependency: RestContextDependency) -> APIRouter | None:
        # The REST routes only serve the old Google calendar shim's callers.
        del ctx_dependency
        return None

    async def test_connection(self, ctx: ConnectionContext) -> ConnectionTestResult:
        try:
            service = self.service_for(ctx)
            message = await service.check_access()
        except CalendarToolError as exc:
            return ConnectionTestResult(ok=False, message=str(exc))
        return ConnectionTestResult(
            ok=True, message=message, account_label=ctx.account_label
        )

    async def list_bookings(
        self, ctx: ConnectionContext, start: datetime, end: datetime
    ) -> Sequence[Booking]:
        try:
            return await self.service_for(ctx).list_bookings(start, end)
        except CalendarToolError as exc:
            raise BookingListFailed(str(exc)) from None

    def service_for(self, ctx: ConnectionContext) -> CalendarService:
        try:
            config = OutlookCalendarConfig.model_validate(dict(ctx.config))
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
            contact_phone=ctx.contact_phone,
            vendor="Microsoft",
        )

    def _client(self, ctx: ConnectionContext) -> GraphCalendarClient:
        if ctx.auth_mode != AuthMode.OAUTH2 or ctx.oauth is None:
            raise NotConfiguredError("this Outlook connection is not usable")
        return GraphCalendarClient(
            http=ctx.http,
            credentials=MicrosoftCredentials(
                connection_id=ctx.connection_id,
                tokens=ctx.oauth,
                cache=self.token_cache,
                scopes_granted=ctx.scopes_granted,
            ),
            account_hint=ctx.account_label,
            timeout=self.request_timeout,
        )
