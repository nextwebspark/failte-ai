"""HTTP request/response models for ``/internal/*``."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr

from fallcha_tools.core.models import (
    AuthMode,
    ConnectionErrorCode,
    ConnectionStatus,
    SyncStatus,
)


class ToolSummary(BaseModel):
    name: str
    description: str = Field(description="What the agent is told (may be long).")
    summary: str | None = Field(
        default=None, description="A short human label, e.g. for the catalog UI."
    )


class CatalogOAuth(BaseModel):
    """OAuth2 details, for providers that support the ``oauth2`` auth mode."""

    scopes: list[str] = Field(description="Always requested; all must be granted.")
    optional_scopes: list[str] = Field(
        description="May be requested with ``optional_scopes`` on oauth/start."
    )
    redirect_uri: str | None = Field(
        default=None,
        description="Register this as an authorized redirect URI of the OAuth "
        "client. None when OAuth is not configured on this deployment.",
    )


class CatalogProvider(BaseModel):
    id: str
    title: str
    description: str
    icon: str
    auth_family: str | None = Field(
        default=None,
        description="Providers of one family share OAuth clients (provider "
        "apps are stored under the family) and service-account keys.",
    )
    share_hint: str | None = Field(
        default=None,
        description="What a service account must be given access to, e.g. "
        "'the spreadsheet'.",
    )
    auth_modes: list[AuthMode]
    scopes: list[str]
    tools: list[ToolSummary]
    config_schema: dict[str, JsonValue] | None = Field(
        default=None, description="JSON Schema of the per-connection config."
    )
    oauth: CatalogOAuth | None = None
    capabilities: list[str] = Field(
        default_factory=list,
        description="Optional features, e.g. ``sync`` (POST "
        "/internal/connections/{id}/sync imports the connection's data).",
    )
    sync_item_label: str | None = Field(
        default=None, description="What a sync imports, e.g. ``products``."
    )


class CatalogResponse(BaseModel):
    providers: list[CatalogProvider]


class SyncStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: SyncStatus
    started_at: datetime
    finished_at: datetime | None
    last_synced_at: datetime | None = Field(
        description="End of the last successful sync."
    )
    item_count: int = Field(description="Items imported (e.g. products).")
    last_error: str | None
    note: str | None = Field(
        default=None,
        description="Caveat of a successful sync, e.g. 'stopped at 2000 pages'.",
    )


class ConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    auth_mode: AuthMode
    account_label: str | None
    scopes_granted: list[str]
    config: dict[str, JsonValue]
    status: ConnectionStatus
    last_error: str | None
    error_code: ConnectionErrorCode | None = Field(
        default=None,
        description="Set when the connection must be reconnected; calls fail "
        "fast until then.",
    )
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    sync: SyncStatusOut | None = Field(
        default=None,
        description="Latest background sync, for providers with the ``sync`` "
        "capability that have been synced at least once.",
    )


class ConnectionList(BaseModel):
    connections: list[ConnectionOut]


class CreateConnectionRequest(BaseModel):
    """Create a connection from directly supplied secrets (non-OAuth modes)."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=64)
    auth_mode: AuthMode
    secret: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="Required, except for the ``none`` auth mode (must be "
        "empty) or with ``reuse_secret_from``.",
    )
    reuse_secret_from: uuid.UUID | None = Field(
        default=None,
        description="Copy the secret (server-side, never returned) of this "
        "active connection of the same org, auth mode and provider family, "
        "instead of sending ``secret``.",
    )
    account_label: str | None = Field(default=None, max_length=320)
    scopes_granted: list[str] = Field(default_factory=list)
    config: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="Non-secret settings, validated by the provider's config model.",
    )


class UpdateConnectionRequest(BaseModel):
    """Update a connection's non-secret config.

    ``config`` is merged into the stored config (top-level keys replace
    stored ones; omitted keys are kept), then the result is validated as on
    create.
    """

    model_config = ConfigDict(extra="forbid")

    config: dict[str, JsonValue]


class IssueKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fallcha_credential_uuid: str | None = Field(default=None, max_length=64)
    exclusive: bool = Field(
        default=False,
        description="Refuse (409) if the connection already has an active key.",
    )


class IssuedKeyOut(BaseModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    key: str = Field(description="Plaintext connection key. Shown only once.")


class ConnectionTestOut(BaseModel):
    ok: bool
    message: str
    connection: ConnectionOut


# -- OAuth2 (bring-your-own client) -------------------------------------------

_CLIENT_ID_PATTERN = r"^[\x21-\x7e]+$"  # printable ASCII, no spaces


class CreateProviderAppRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=64)
    client_id: str = Field(min_length=1, max_length=256, pattern=_CLIENT_ID_PATTERN)
    client_secret: SecretStr = Field(min_length=1, max_length=512)


class ProviderAppOut(BaseModel):
    """An OAuth client. The secret is write-only."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str = Field(
        description="The provider's auth family (e.g. ``google``), else its id: "
        "a client can start the flow for every provider of that family."
    )
    client_id: str
    created_by: int | None
    created_at: datetime
    updated_at: datetime


class ProviderAppList(BaseModel):
    provider_apps: list[ProviderAppOut]


class OAuthStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=64)
    provider_app_id: uuid.UUID
    optional_scopes: list[str] = Field(default_factory=list, max_length=16)
    login_hint: str | None = Field(
        default=None,
        max_length=320,
        pattern=r"^[^\s@]+@[^\s@]+$",
        description="Email of the account to suggest (e.g. the one an existing "
        "connection of the same family uses), so the provider can skip the "
        "account chooser and ask only for the new scopes.",
    )


class OAuthStartOut(BaseModel):
    authorization_url: str = Field(description="Send the user's browser here.")
    redirect_uri: str = Field(
        description="Must be registered as an authorized redirect URI of the "
        "OAuth client."
    )
    expires_at: datetime = Field(description="The flow must finish before this.")
    browser_nonce: str = Field(
        description="For the starting user's browser tab only (the Fallcha API "
        "returns it in the start response); required to confirm the connection."
    )


class ConfirmConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    browser_nonce: SecretStr = Field(min_length=1, max_length=128)
