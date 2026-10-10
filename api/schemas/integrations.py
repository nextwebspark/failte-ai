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
    """A workspace OAuth client. The secret is write-only."""

    id: uuid.UUID
    provider: str = Field(
        description="The auth family (e.g. ``google``) or provider id the "
        "client serves: it can be used for every provider of that family."
    )
    client_id: str
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime


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
