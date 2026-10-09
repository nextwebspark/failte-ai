"""Data access. The only module that builds queries; callers get dataclasses.

Every method that touches an org-scoped row takes ``org_id`` and filters on
it in SQL, so one workspace can never read or change another's rows.
Write methods commit their own unit of work.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import JsonValue
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fallcha_tools.core.crypto import SecretBox
from fallcha_tools.core.errors import ConflictError, NotFoundError
from fallcha_tools.core.keys import (
    generate_connection_key,
    hash_connection_key,
    looks_like_connection_key,
)
from fallcha_tools.core.models import (
    AuthMode,
    Connection,
    ConnectionKey,
    ConnectionStatus,
)


class ConnectionNotFoundError(NotFoundError):
    pass


class ConnectionRevokedError(ConflictError):
    pass


@dataclass(frozen=True, slots=True)
class ConnectionInfo:
    """A connection without any secret material."""

    id: uuid.UUID
    org_id: int
    provider: str
    auth_mode: AuthMode
    account_label: str | None
    scopes_granted: tuple[str, ...]
    status: ConnectionStatus
    last_error: str | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ConnectionSecrets:
    info: ConnectionInfo
    secret: Mapping[str, JsonValue]
    access_token: str | None


@dataclass(frozen=True, slots=True)
class IssuedKey:
    """A freshly issued key. ``key`` is plaintext and is never stored."""

    id: uuid.UUID
    connection_id: uuid.UUID
    key: str


@dataclass(frozen=True, slots=True)
class KeyPrincipal:
    """Who a valid connection key acts for."""

    key_id: uuid.UUID
    org_id: int
    connection_id: uuid.UUID
    provider: str


def _info(row: Connection) -> ConnectionInfo:
    return ConnectionInfo(
        id=row.id,
        org_id=row.org_id,
        provider=row.provider,
        auth_mode=row.auth_mode,
        account_label=row.account_label,
        scopes_granted=tuple(row.scopes_granted or ()),
        status=row.status,
        last_error=row.last_error,
        expires_at=row.expires_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ConnectionRepository:
    def __init__(self, session: AsyncSession, box: SecretBox) -> None:
        self._session = session
        self._box = box

    async def create_connection(
        self,
        *,
        org_id: int,
        provider: str,
        auth_mode: AuthMode,
        secret: Mapping[str, JsonValue] | None,
        account_label: str | None = None,
        scopes_granted: tuple[str, ...] = (),
        created_by: int | None = None,
        provider_app_id: uuid.UUID | None = None,
        access_token: str | None = None,
        expires_at: datetime | None = None,
    ) -> ConnectionInfo:
        row = Connection(
            org_id=org_id,
            provider=provider,
            auth_mode=auth_mode,
            provider_app_id=provider_app_id,
            account_label=account_label,
            scopes_granted=list(scopes_granted),
            secret_enc=self._box.encrypt_json(dict(secret)) if secret else None,
            access_token_enc=self._box.encrypt(access_token) if access_token else None,
            expires_at=expires_at,
            status=ConnectionStatus.ACTIVE,
            created_by=created_by,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _info(row)

    async def list_connections(
        self, org_id: int, *, include_revoked: bool = False
    ) -> list[ConnectionInfo]:
        query = select(Connection).where(Connection.org_id == org_id)
        if not include_revoked:
            query = query.where(Connection.status != ConnectionStatus.REVOKED)
        rows = await self._session.scalars(query.order_by(Connection.created_at))
        return [_info(row) for row in rows]

    async def get_connection(
        self, org_id: int, connection_id: uuid.UUID
    ) -> ConnectionInfo:
        return _info(await self._get_row(org_id, connection_id))

    async def load_secrets(
        self, org_id: int, connection_id: uuid.UUID
    ) -> ConnectionSecrets:
        row = await self._get_row(org_id, connection_id)
        if row.status == ConnectionStatus.REVOKED:
            raise ConnectionRevokedError("connection has been revoked")
        secret: Mapping[str, JsonValue] = {}
        if row.secret_enc:
            decoded = self._box.decrypt_json(row.secret_enc)
            if isinstance(decoded, dict):
                secret = decoded
        access_token = (
            self._box.decrypt(row.access_token_enc) if row.access_token_enc else None
        )
        return ConnectionSecrets(
            info=_info(row), secret=secret, access_token=access_token
        )

    async def set_status(
        self,
        org_id: int,
        connection_id: uuid.UUID,
        status: ConnectionStatus,
        *,
        last_error: str | None = None,
        account_label: str | None = None,
    ) -> ConnectionInfo:
        row = await self._get_row(org_id, connection_id)
        if row.status == ConnectionStatus.REVOKED:
            raise ConnectionRevokedError("connection has been revoked")
        row.status = status
        row.last_error = last_error
        if account_label is not None:
            row.account_label = account_label
        await self._session.commit()
        await self._session.refresh(row)
        return _info(row)

    async def revoke_connection(self, org_id: int, connection_id: uuid.UUID) -> None:
        """Revoke every key, wipe secrets, and mark the connection revoked."""
        row = await self._get_row(org_id, connection_id)
        await self._session.execute(
            update(ConnectionKey)
            .where(
                ConnectionKey.connection_id == row.id,
                ConnectionKey.org_id == org_id,
                ConnectionKey.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        row.status = ConnectionStatus.REVOKED
        row.secret_enc = None
        row.access_token_enc = None
        row.expires_at = None
        await self._session.commit()

    async def _get_row(self, org_id: int, connection_id: uuid.UUID) -> Connection:
        row = await self._session.scalar(
            select(Connection).where(
                Connection.id == connection_id, Connection.org_id == org_id
            )
        )
        if row is None:
            raise ConnectionNotFoundError("connection not found")
        return row


class KeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def issue_key(
        self,
        *,
        org_id: int,
        connection_id: uuid.UUID,
        fallcha_credential_uuid: str | None = None,
        created_by: int | None = None,
    ) -> IssuedKey:
        connection = await self._session.scalar(
            select(Connection).where(
                Connection.id == connection_id, Connection.org_id == org_id
            )
        )
        if connection is None:
            raise ConnectionNotFoundError("connection not found")
        if connection.status == ConnectionStatus.REVOKED:
            raise ConnectionRevokedError("connection has been revoked")
        key = generate_connection_key()
        row = ConnectionKey(
            key_hash=hash_connection_key(key),
            connection_id=connection.id,
            org_id=org_id,
            fallcha_credential_uuid=fallcha_credential_uuid,
            created_by=created_by,
        )
        self._session.add(row)
        await self._session.commit()
        return IssuedKey(id=row.id, connection_id=connection.id, key=key)

    async def lookup_key(self, key: str) -> KeyPrincipal | None:
        """Resolve a plaintext key; None if unknown, revoked, or its
        connection is revoked."""
        if not looks_like_connection_key(key):
            return None
        result = await self._session.execute(
            select(
                ConnectionKey.id, Connection.org_id, Connection.id, Connection.provider
            )
            .join(Connection, Connection.id == ConnectionKey.connection_id)
            .where(
                ConnectionKey.key_hash == hash_connection_key(key),
                ConnectionKey.revoked_at.is_(None),
                ConnectionKey.org_id == Connection.org_id,
                Connection.status != ConnectionStatus.REVOKED,
            )
        )
        found = result.one_or_none()
        if found is None:
            return None
        key_id, org_id, connection_id, provider = found
        return KeyPrincipal(
            key_id=key_id, org_id=org_id, connection_id=connection_id, provider=provider
        )
