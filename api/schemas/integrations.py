"""Request/response schemas for catalog integrations (``/integrations``).

Catalog integrations are third-party providers hosted by the Fallcha tools
service. Installing one creates a connection there, plus a bearer credential
and an MCP tool in the workspace. Not to be confused with the post-call
integrations under ``api/services/integrations``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SecretStr,
    model_validator,
)

PROVIDER_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"

DirectAuthMode = Literal["service_account", "api_key", "none"]


class IntegrationToolSummary(BaseModel):
    """One function a provider exposes to agents."""

    name: str
    description: str = Field(description="What the agent is told (may be long).")
    summary: str | None = Field(
        default=None, description="A short human label for the function."
    )


class IntegrationOAuthInfo(BaseModel):
    """OAuth2 scopes of a provider that supports the ``oauth2`` auth mode."""

    scopes: list[str] = Field(description="Always requested; all must be granted.")
    optional_scopes: list[str] = Field(
        description="May be requested with ``optional_scopes`` on oauth/start."
    )
    redirect_uri: str | None = Field(
        default=None,
        description="Register this as an authorized redirect URI of the OAuth "
        "client. None when OAuth is not configured on this deployment.",
    )


class IntegrationProvider(BaseModel):
    """A provider in the platform catalog, the same for every workspace."""

    id: str
    title: str
    description: str
    icon: str
    auth_family: str | None = Field(
        default=None,
        description="Providers of one family (e.g. ``google``) share OAuth "
        "clients and can reuse each other's service-account keys.",
    )
    share_hint: str | None = Field(
        default=None,
        description="What a service account must be given access to, e.g. "
        "'the spreadsheet'.",
    )
    auth_modes: list[str]
    scopes: list[str]
    tools: list[IntegrationToolSummary]
    config_schema: dict[str, JsonValue] | None = Field(
        default=None, description="JSON Schema of the per-connection config."
    )
    oauth: IntegrationOAuthInfo | None = None
    capabilities: list[str] = Field(
        default_factory=list,
        description="Optional features, e.g. ``sync`` (POST "
        "/connections/{id}/sync imports the connection's data).",
    )
    sync_item_label: str | None = Field(
        default=None, description="What a sync imports, e.g. ``products``."
    )


class IntegrationCatalogResponse(BaseModel):
    providers: list[IntegrationProvider]


class IntegrationSyncStatus(BaseModel):
    """The latest background sync of a connection (``sync`` capability)."""

    status: str = Field(description="running, succeeded or failed.")
    started_at: datetime
    finished_at: datetime | None = None
    last_synced_at: datetime | None = Field(
        default=None, description="End of the last successful sync."
    )
    item_count: int = Field(description="Items imported, e.g. products.")
    last_error: str | None = None
    note: str | None = Field(
        default=None,
        description="Caveat of a successful sync, e.g. 'stopped at 2000 pages'.",
    )


class IntegrationConnection(BaseModel):
    """A workspace's connection to a provider, as the tools service reports
    it. Never includes secrets."""

    id: uuid.UUID
    provider: str
    auth_mode: str
    account_label: str | None = None
    scopes_granted: list[str] = Field(default_factory=list)
    config: dict[str, JsonValue] = Field(default_factory=dict)
    status: str = Field(description="pending, active, error or revoked.")
    last_error: str | None = None
    error_code: str | None = Field(
        default=None,
        description="Set (e.g. grant_revoked) when only reconnecting can help.",
    )
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    sync: IntegrationSyncStatus | None = Field(
        default=None,
        description="Latest sync, for providers with the ``sync`` capability.",
    )


class IntegrationConnectionResponse(IntegrationConnection):
    """A connection plus the workspace resources installed for it."""

    credential_uuid: str | None = Field(
        default=None,
        description="Bearer credential holding this connection's key, if any.",
    )
    tool_uuids: list[str] = Field(
        default_factory=list,
        description="Active MCP tools that authenticate with that credential.",
    )


class IntegrationConnectionListResponse(BaseModel):
    connections: list[IntegrationConnectionResponse]


class InstallIntegrationRequest(BaseModel):
    """Connect a provider with directly supplied secrets, and install it as an
    MCP tool. OAuth2 providers connect through their own flow instead."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(pattern=PROVIDER_ID_PATTERN, description="Catalog id.")
    auth_mode: DirectAuthMode
    secret: dict[str, JsonValue] = Field(
        default_factory=dict,
        description=(
            "Provider secret, e.g. a service-account JSON key. Stored encrypted "
            "by the tools service; never returned. Empty for the ``none`` auth "
            "mode, or with ``reuse_secret_from``."
        ),
    )
    reuse_secret_from: uuid.UUID | None = Field(
        default=None,
        description="Reuse the secret of this workspace's active connection of "
        "the same provider family and auth mode (e.g. the service account "
        "already connected for Google Calendar). Copied by the tools service; "
        "never sent to the browser.",
    )
    account_label: str | None = Field(default=None, max_length=320)
    scopes_granted: list[str] = Field(default_factory=list)
    config: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="Non-secret settings, validated against the provider's "
        "config_schema.",
    )
    tool_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Name of the created tool. Defaults to the provider title.",
    )

    @model_validator(mode="after")
    def _secret_source(self) -> Self:
        if self.auth_mode == "none":
            if self.secret or self.reuse_secret_from:
                raise ValueError("the none auth mode takes no secret")
        elif bool(self.secret) == bool(self.reuse_secret_from):
            raise ValueError("give either secret or reuse_secret_from")
        return self


class UpdateIntegrationConfigRequest(BaseModel):
    """Merge ``config`` into the stored config: given top-level keys replace
    stored ones, omitted keys are kept."""

    model_config = ConfigDict(extra="forbid")

    config: dict[str, JsonValue]


class IntegrationTestResponse(BaseModel):
    ok: bool
    message: str
    connection: IntegrationConnectionResponse


class ActivateIntegrationRequest(BaseModel):
    """Install an existing connection (e.g. one just created by the OAuth
    callback) as an MCP tool."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Name of the created tool. Defaults to the provider title.",
    )
    browser_nonce: SecretStr | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="The ``browser_nonce`` from ``oauth/start``. Required to "
        "confirm a just-authorized (pending) OAuth connection; ignored otherwise.",
    )


# -- OAuth2 (bring-your-own client) -------------------------------------------


class CreateProviderAppRequest(BaseModel):
    """Save the workspace's own OAuth client for a provider."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(pattern=PROVIDER_ID_PATTERN, description="Catalog id.")
    client_id: str = Field(min_length=1, max_length=256)
    client_secret: SecretStr = Field(
        min_length=1,
        max_length=512,
        description="Stored encrypted by the tools service; never returned.",
    )


class ProviderAppResponse(BaseModel):
    """An OAuth client the workspace can use. The secret is write-only."""

    id: uuid.UUID
    provider: str = Field(
        description="The auth family (e.g. ``google``) or provider id the "
        "client serves: it can be used for every provider of that family."
    )
    client_id: str
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime
    managed: bool = Field(
        default=False,
        description="The platform's own client, offered to every workspace "
        "(listed first). It cannot be deleted.",
    )


class ProviderAppListResponse(BaseModel):
    provider_apps: list[ProviderAppResponse]


class StartOAuthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(pattern=PROVIDER_ID_PATTERN, description="Catalog id.")
    provider_app_id: uuid.UUID = Field(description="The OAuth client to use.")
    optional_scopes: list[str] = Field(
        default_factory=list,
        max_length=16,
        description="Any of the provider's ``oauth.optional_scopes``.",
    )
    login_hint: str | None = Field(
        default=None,
        max_length=320,
        pattern=r"^[^\s@]+@[^\s@]+$",
        description="Email of the account to suggest, e.g. the one an "
        "existing connection of the same family uses, so the provider can "
        "skip the account chooser and ask only for the new permissions.",
    )


class StartOAuthResponse(BaseModel):
    authorization_url: str = Field(description="Send the user's browser here.")
    redirect_uri: str = Field(
        description="Must be registered as an authorized redirect URI of the "
        "OAuth client."
    )
    expires_at: datetime = Field(description="The flow must finish before this.")
    browser_nonce: str = Field(
        description="Keep in this browser only (e.g. sessionStorage) and send it "
        "to ``activate`` when the provider redirects back. It binds the new "
        "connection to the user and browser that started the flow."
    )


class IntegrationBooking(BaseModel):
    """One booking an agent made, read back from the calendar by the tools
    service (providers with the ``bookings`` capability)."""

    event_id: str
    start: datetime
    end: datetime
    status: Literal["confirmed", "cancelled"]
    caller_name: str | None = None
    caller_phone: str | None = None
    party_size: int | None = None
    reason: str | None = None
    created_at: datetime | None = None


class CalendarBooking(IntegrationBooking):
    connection_id: uuid.UUID = Field(description="The calendar it is on.")


class BookingCalendar(BaseModel):
    """A connected calendar the bookings were read from."""

    connection_id: uuid.UUID
    provider: str
    title: str = Field(description="Provider name, e.g. Google Calendar.")
    account_label: str | None = None
    ai_booking_enabled: bool = Field(
        description="Whether agents may book on it (the owner's switch)."
    )
    ai_changes_enabled: bool = Field(
        default=False,
        description="Whether agents may cancel or move bookings made on an "
        "earlier call, after checking the caller's details.",
    )
    rules: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="The calendar's current booking rules (owner-editable "
        "keys only; missing ones use the defaults).",
    )
    ok: bool = Field(description="False when its bookings could not be read.")
    error: str | None = Field(
        default=None, description="Why not, in words an admin can act on."
    )


class BookingServicePeriod(BaseModel):
    """When bookings may start on some weekdays, e.g. dinner Thu-Sat."""

    model_config = ConfigDict(extra="forbid")

    days: list[int] = Field(min_length=1, description="Monday=0 ... Sunday=6.")
    first_start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    last_start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class BookingRules(BaseModel):
    """The booking rules an owner sets in plain terms. Omitted rules are
    kept; the tools service checks the combination (e.g. a party limit above
    the covers limit) and answers 422 with the reason."""

    model_config = ConfigDict(extra="forbid")

    service_periods: list[BookingServicePeriod] | None = Field(
        default=None, max_length=21
    )
    slot_minutes: int | None = Field(default=None, ge=5, le=240)
    booking_minutes: int | None = Field(default=None, ge=5, le=720)
    buffer_minutes: int | None = Field(default=None, ge=0, le=240)
    max_bookings_at_once: int | None = Field(default=None, ge=1, le=500)
    max_guests_at_once: int | None = Field(default=None, ge=1, le=10000)
    max_party_size: int | None = Field(default=None, ge=1, le=100)
    min_lead_hours: int | None = Field(default=None, ge=0, le=168)
    horizon_days: int | None = Field(default=None, ge=1, le=60)


# Calendar settings the owner (bookings:manage) may change.
OWNER_RULE_KEYS = frozenset(BookingRules.model_fields)


class AiBookingRequest(BaseModel):
    """The owner's switches and booking rules for one calendar; omitted
    ones are kept."""

    model_config = ConfigDict(extra="forbid")

    ai_booking_enabled: bool | None = None
    ai_changes_enabled: bool | None = None
    rules: BookingRules | None = None

    @model_validator(mode="after")
    def _something(self) -> Self:
        if (
            self.ai_booking_enabled is None
            and self.ai_changes_enabled is None
            and not (self.rules and self.rules.model_dump(exclude_none=True))
        ):
            raise ValueError("give ai_booking_enabled, ai_changes_enabled or rules")
        return self

    def changes(self) -> dict[str, JsonValue]:
        changes: dict[str, JsonValue] = self.model_dump(
            exclude_none=True, exclude={"rules"}
        )
        if self.rules:
            changes.update(self.rules.model_dump(exclude_none=True))
        return changes


class BookingListResponse(BaseModel):
    """Bookings in the requested range across the workspace's calendars, in
    start order, with cancelled ones marked."""

    calendars: list[BookingCalendar]
    bookings: list[CalendarBooking]
