"""Request/response schemas for catalog integrations (``/integrations``).

Catalog integrations are third-party providers hosted by the Fallcha tools
service. Installing one creates a connection there, plus a bearer credential
and an MCP tool in the workspace. Not to be confused with the post-call
integrations under ``api/services/integrations``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr

PROVIDER_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"

DirectAuthMode = Literal["service_account", "api_key"]


class IntegrationToolSummary(BaseModel):
    """One function a provider exposes to agents."""

    name: str
    description: str


class IntegrationOAuthInfo(BaseModel):
    """OAuth2 scopes of a provider that supports the ``oauth2`` auth mode."""

    scopes: list[str] = Field(description="Always requested; all must be granted.")
    optional_scopes: list[str] = Field(
        description="May be requested with ``optional_scopes`` on oauth/start."
    )


class IntegrationProvider(BaseModel):
    """A provider in the platform catalog, the same for every workspace."""

    id: str
    title: str
    description: str
    icon: str
    auth_modes: list[str]
    scopes: list[str]
    tools: list[IntegrationToolSummary]
    config_schema: dict[str, JsonValue] | None = Field(
        default=None, description="JSON Schema of the per-connection config."
    )
    oauth: IntegrationOAuthInfo | None = None


class IntegrationCatalogResponse(BaseModel):
    providers: list[IntegrationProvider]


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
        min_length=1,
        description=(
            "Provider secret, e.g. a service-account JSON key. Stored encrypted "
            "by the tools service; never returned."
        ),
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
    provider: str
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


class StartOAuthResponse(BaseModel):
    authorization_url: str = Field(description="Send the user's browser here.")
    redirect_uri: str = Field(
        description="Must be registered as an authorized redirect URI of the "
        "OAuth client."
    )
    expires_at: datetime = Field(description="The flow must finish before this.")
