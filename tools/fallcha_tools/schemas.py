"""HTTP request/response models for ``/internal/*``."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from fallcha_tools.core.models import AuthMode, ConnectionStatus


class ToolSummary(BaseModel):
    name: str
    description: str


class CatalogProvider(BaseModel):
    id: str
    title: str
    description: str
    icon: str
    auth_modes: list[AuthMode]
    scopes: list[str]
    tools: list[ToolSummary]


class CatalogResponse(BaseModel):
    providers: list[CatalogProvider]


class ConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    auth_mode: AuthMode
    account_label: str | None
    scopes_granted: list[str]
    status: ConnectionStatus
    last_error: str | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConnectionList(BaseModel):
    connections: list[ConnectionOut]


class CreateConnectionRequest(BaseModel):
    """Create a connection from directly supplied secrets (non-OAuth modes)."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=64)
    auth_mode: AuthMode
    secret: dict[str, JsonValue] = Field(min_length=1)
    account_label: str | None = Field(default=None, max_length=320)
    scopes_granted: list[str] = Field(default_factory=list)


class IssueKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fallcha_credential_uuid: str | None = Field(default=None, max_length=64)


class IssuedKeyOut(BaseModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    key: str = Field(description="Plaintext connection key. Shown only once.")


class ConnectionTestOut(BaseModel):
    ok: bool
    message: str
    connection: ConnectionOut
