"""ORM models. Every table lives in the ``fallcha_tools`` Postgres schema.

Columns ending in ``_enc`` hold :class:`~fallcha_tools.core.crypto.SecretBox`
ciphertext as text; plaintext secrets are never persisted.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "fallcha_tools"


class AuthMode(StrEnum):
    OAUTH2 = "oauth2"
    SERVICE_ACCOUNT = "service_account"
    API_KEY = "api_key"
    # Public data only (e.g. a website's catalogue): the connection holds no
    # secret, but tool calls still need the connection key.
    NONE = "none"


class ConnectionStatus(StrEnum):
    # OAuth2 connections start PENDING: created by the callback, but unusable
    # until the user who started the flow confirms it from the same browser.
    PENDING = "pending"
    ACTIVE = "active"
    ERROR = "error"
    REVOKED = "revoked"


class ConnectionErrorCode(StrEnum):
    """Why a connection is in ERROR when retrying cannot help: calls fail
    fast, without asking the provider, until the workspace reconnects."""

    GRANT_REVOKED = "grant_revoked"
    CLIENT_REJECTED = "client_rejected"
    CLIENT_MISSING = "client_missing"


class SyncStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def _str_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    # VARCHAR + CHECK instead of a native PG enum: adding a value later is a
    # plain constraint swap rather than an ALTER TYPE dance.
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )


class Base(DeclarativeBase):
    metadata = MetaData(
        schema=SCHEMA,
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        },
    )


class _Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ProviderApp(_Timestamps, Base):
    """A bring-your-own OAuth client. ``org_id`` NULL means the platform app."""

    __tablename__ = "provider_apps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    client_id: Mapped[str] = mapped_column(Text, nullable=False)
    client_secret_enc: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (Index(None, "org_id", "provider"),)


class Connection(_Timestamps, Base):
    """A workspace's authenticated link to one provider."""

    __tablename__ = "connections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    auth_mode: Mapped[AuthMode] = mapped_column(
        _str_enum(AuthMode, "auth_mode"), nullable=False
    )
    provider_app_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider_apps.id", ondelete="SET NULL"),
        nullable=True,
    )
    account_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes_granted: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    # Non-secret, provider-validated settings (calendar id, time zone, ...).
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[ConnectionStatus] = mapped_column(
        _str_enum(ConnectionStatus, "connection_status"),
        nullable=False,
        default=ConnectionStatus.ACTIVE,
        server_default=ConnectionStatus.ACTIVE.value,
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[ConnectionErrorCode | None] = mapped_column(
        _str_enum(ConnectionErrorCode, "connection_error_code"), nullable=True
    )
    # PENDING only: who may confirm it, and the SHA-256 of their browser nonce.
    pending_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pending_nonce_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (Index(None, "org_id", "provider"),)


class ConnectionKey(Base):
    """An opaque bearer key that Fallcha stores to reach one connection."""

    __tablename__ = "connection_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    fallcha_credential_uuid: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class OAuthState(Base):
    """Short-lived OAuth2 authorization state (PKCE verifier and context)."""

    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(128), primary_key=True)
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_app_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider_apps.id", ondelete="CASCADE"),
        nullable=True,
    )
    code_verifier_enc: Mapped[str] = mapped_column(Text, nullable=False)
    # SHA-256 of the nonce returned to the starting user's browser tab.
    browser_nonce_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    redirect_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class ConnectionSync(Base):
    """The latest background sync of a connection whose provider imports
    data (e.g. a website catalogue). One row per connection."""

    __tablename__ = "connection_syncs"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("connections.id", ondelete="CASCADE"),
        primary_key=True,
    )
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    status: Mapped[SyncStatus] = mapped_column(
        _str_enum(SyncStatus, "sync_status"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Bumped while a sync runs; a RUNNING row with a stale heartbeat was
    # interrupted (e.g. the process restarted).
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The end of the last successful sync, and how many items it holds.
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
