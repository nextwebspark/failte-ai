"""Data access. The only module that builds queries; callers get dataclasses.

Every method that touches an org-scoped row takes ``org_id`` and filters on
it in SQL, so one workspace can never read or change another's rows.
Write methods commit their own unit of work.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import JsonValue
from sqlalchemy import delete, func, select, update
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
    OAuthState,
    ProviderApp,
)

# Key in an OAuth2 connection's encrypted secret.
REFRESH_TOKEN_KEY = "refresh_token"


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
    config: Mapping[str, JsonValue]
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


class ProviderAppNotFoundError(NotFoundError):
    pass


class KeyConflictError(ConflictError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderAppInfo:
    """A bring-your-own OAuth client, without its secret."""

    id: uuid.UUID
    org_id: int | None
    provider: str
    client_id: str
    created_by: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class OAuthClient:
    """Decrypted OAuth client credentials. Never logged or returned."""

    client_id: str
    client_secret: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class PendingAuthorization:
    """A consumed OAuth state: who started the flow, and its PKCE verifier."""

    org_id: int
    user_id: int | None
    provider: str
    provider_app_id: uuid.UUID | None
    code_verifier: str = field(repr=False)
    redirect_uri: str | None
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class RefreshState:
    """An OAuth2 connection's tokens, read under the refresh locks."""

    status: ConnectionStatus
    access_token: str | None = field(repr=False)
    expires_at: datetime | None
    refresh_token: str | None = field(repr=False)
    client: OAuthClient | None


@dataclass(frozen=True, slots=True)
class KeyPrincipal:
    """Who a valid connection key acts for."""

    key_id: uuid.UUID
    org_id: int
    connection_id: uuid.UUID
    provider: str


def _app_info(row: ProviderApp) -> ProviderAppInfo:
    return ProviderAppInfo(
        id=row.id,
        org_id=row.org_id,
        provider=row.provider,
        client_id=row.client_id,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def hash_oauth_state(state: str) -> str:
    """States are stored hashed: a database read never yields a usable one,
    and lookups compare digests, not the secret itself."""
    return hashlib.sha256(state.encode()).hexdigest()


def refresh_lock_id(connection_id: uuid.UUID) -> int:
    """The signed 64-bit advisory-lock id for refreshing one connection."""
    digest = hashlib.sha256(
        b"fallcha_tools.oauth_refresh:" + connection_id.bytes
    ).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def _info(row: Connection) -> ConnectionInfo:
    return ConnectionInfo(
        id=row.id,
        org_id=row.org_id,
        provider=row.provider,
        auth_mode=row.auth_mode,
        account_label=row.account_label,
        scopes_granted=tuple(row.scopes_granted or ()),
        config=dict(row.config or {}),
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
        config: Mapping[str, JsonValue] | None = None,
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
            config=dict(config or {}),
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
        row = await self._get_row(org_id, connection_id, for_update=True)
        if row.status == ConnectionStatus.REVOKED:
            raise ConnectionRevokedError("connection has been revoked")
        row.status = status
        row.last_error = last_error
        if account_label is not None:
            row.account_label = account_label
        await self._session.commit()
        await self._session.refresh(row)
        return _info(row)

    async def update_config(
        self, org_id: int, connection_id: uuid.UUID, config: Mapping[str, JsonValue]
    ) -> ConnectionInfo:
        """Replace the connection's (already validated) non-secret config."""
        row = await self._get_row(org_id, connection_id, for_update=True)
        if row.status == ConnectionStatus.REVOKED:
            raise ConnectionRevokedError("connection has been revoked")
        row.config = dict(config)
        await self._session.commit()
        await self._session.refresh(row)
        return _info(row)

    async def revoke_connection(self, org_id: int, connection_id: uuid.UUID) -> None:
        """Revoke every key, wipe secrets, and mark the connection revoked."""
        row = await self._get_row(org_id, connection_id, for_update=True)
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

    async def _get_row(
        self, org_id: int, connection_id: uuid.UUID, *, for_update: bool = False
    ) -> Connection:
        query = select(Connection).where(
            Connection.id == connection_id, Connection.org_id == org_id
        )
        if for_update:
            # Row lock + fresh read: a concurrent revoke and a status write
            # serialize, and a revoked row is never flipped back to active.
            query = query.with_for_update().execution_options(populate_existing=True)
        row = await self._session.scalar(query)
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
        exclusive: bool = False,
    ) -> IssuedKey:
        """Issue a key. With ``exclusive``, refuse (409) if the connection
        already has an unrevoked key; the connection row lock makes that
        check race-free, so concurrent activations issue exactly one key."""
        connection = await self._session.scalar(
            select(Connection)
            .where(Connection.id == connection_id, Connection.org_id == org_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if connection is None:
            raise ConnectionNotFoundError("connection not found")
        if connection.status == ConnectionStatus.REVOKED:
            raise ConnectionRevokedError("connection has been revoked")
        if exclusive:
            active = await self._session.scalar(
                select(func.count())
                .select_from(ConnectionKey)
                .where(
                    ConnectionKey.connection_id == connection.id,
                    ConnectionKey.org_id == org_id,
                    ConnectionKey.revoked_at.is_(None),
                )
            )
            if active:
                raise KeyConflictError("connection already has an active key")
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

    async def revoke_key(
        self, org_id: int, connection_id: uuid.UUID, key_id: uuid.UUID
    ) -> None:
        """Revoke one key (idempotent); 404 if it is not this org's."""
        row = await self._session.scalar(
            select(ConnectionKey).where(
                ConnectionKey.id == key_id,
                ConnectionKey.connection_id == connection_id,
                ConnectionKey.org_id == org_id,
            )
        )
        if row is None:
            raise NotFoundError("connection key not found")
        if row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            await self._session.commit()

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


class ProviderAppRepository:
    """Org-owned OAuth clients. Platform apps (``org_id`` NULL) are not
    managed here."""

    def __init__(self, session: AsyncSession, box: SecretBox) -> None:
        self._session = session
        self._box = box

    async def create(
        self,
        *,
        org_id: int,
        provider: str,
        client_id: str,
        client_secret: str,
        created_by: int | None,
    ) -> ProviderAppInfo:
        row = ProviderApp(
            org_id=org_id,
            provider=provider,
            client_id=client_id,
            client_secret_enc=self._box.encrypt(client_secret),
            created_by=created_by,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _app_info(row)

    async def list_apps(self, org_id: int) -> list[ProviderAppInfo]:
        rows = await self._session.scalars(
            select(ProviderApp)
            .where(ProviderApp.org_id == org_id)
            .order_by(ProviderApp.created_at)
        )
        return [_app_info(row) for row in rows]

    async def get(self, org_id: int, app_id: uuid.UUID) -> ProviderAppInfo:
        return _app_info(await self._get_row(org_id, app_id))

    async def client(self, org_id: int, app_id: uuid.UUID) -> OAuthClient:
        row = await self._get_row(org_id, app_id)
        return OAuthClient(
            client_id=row.client_id,
            client_secret=self._box.decrypt(row.client_secret_enc),
        )

    async def delete_app(self, org_id: int, app_id: uuid.UUID) -> None:
        """Delete the app (and its pending states). Refused while a live
        connection still refreshes its tokens with it."""
        row = await self._get_row(org_id, app_id, for_update=True)
        in_use = await self._session.scalar(
            select(func.count())
            .select_from(Connection)
            .where(
                Connection.provider_app_id == row.id,
                Connection.org_id == org_id,
                Connection.status != ConnectionStatus.REVOKED,
            )
        )
        if in_use:
            raise ConflictError(
                f"this OAuth client is used by {in_use} connection(s); "
                "remove them first"
            )
        await self._session.delete(row)
        await self._session.commit()

    async def _get_row(
        self, org_id: int, app_id: uuid.UUID, *, for_update: bool = False
    ) -> ProviderApp:
        query = select(ProviderApp).where(
            ProviderApp.id == app_id, ProviderApp.org_id == org_id
        )
        if for_update:
            query = query.with_for_update()
        row = await self._session.scalar(query)
        if row is None:
            raise ProviderAppNotFoundError("OAuth client not found")
        return row


class OAuthStateRepository:
    def __init__(self, session: AsyncSession, box: SecretBox) -> None:
        self._session = session
        self._box = box

    async def create(
        self,
        *,
        state: str,
        org_id: int,
        user_id: int,
        provider: str,
        provider_app_id: uuid.UUID,
        code_verifier: str,
        redirect_uri: str,
        expires_at: datetime,
        now: datetime,
    ) -> None:
        # Housekeeping: expired states are useless; drop them as we go.
        await self._session.execute(
            delete(OAuthState).where(OAuthState.expires_at < now)
        )
        self._session.add(
            OAuthState(
                state=hash_oauth_state(state),
                org_id=org_id,
                user_id=user_id,
                provider=provider,
                provider_app_id=provider_app_id,
                code_verifier_enc=self._box.encrypt(code_verifier),
                redirect_uri=redirect_uri,
                expires_at=expires_at,
            )
        )
        await self._session.commit()

    async def consume(self, state: str) -> PendingAuthorization | None:
        """Delete and return the state in one statement (single use: of two
        concurrent callbacks with the same state, only one gets it). Expiry
        is the caller's check, so an expired state is consumed too."""
        row = (
            await self._session.execute(
                delete(OAuthState)
                .where(OAuthState.state == hash_oauth_state(state))
                .returning(
                    OAuthState.org_id,
                    OAuthState.user_id,
                    OAuthState.provider,
                    OAuthState.provider_app_id,
                    OAuthState.code_verifier_enc,
                    OAuthState.redirect_uri,
                    OAuthState.expires_at,
                )
            )
        ).one_or_none()
        await self._session.commit()
        if row is None:
            return None
        return PendingAuthorization(
            org_id=row.org_id,
            user_id=row.user_id,
            provider=row.provider,
            provider_app_id=row.provider_app_id,
            code_verifier=self._box.decrypt(row.code_verifier_enc),
            redirect_uri=row.redirect_uri,
            expires_at=row.expires_at,
        )


class OAuthTokenRepository:
    """Reads and writes one OAuth2 connection's tokens inside a refresh
    transaction. The caller owns the transaction: :meth:`lock` and
    :meth:`load` hold their locks until :meth:`save` / :meth:`mark_error`
    commit, or the session rolls back."""

    def __init__(self, session: AsyncSession, box: SecretBox) -> None:
        self._session = session
        self._box = box
        self._row: Connection | None = None

    async def lock(self, connection_id: uuid.UUID) -> None:
        """Serialize refreshes of one connection across processes."""
        await self._session.execute(
            select(func.pg_advisory_xact_lock(refresh_lock_id(connection_id)))
        )

    async def load(self, org_id: int, connection_id: uuid.UUID) -> RefreshState:
        row = await self._session.scalar(
            select(Connection)
            .where(
                Connection.id == connection_id,
                Connection.org_id == org_id,
                Connection.auth_mode == AuthMode.OAUTH2,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise ConnectionNotFoundError("connection not found")
        if row.status == ConnectionStatus.REVOKED:
            raise ConnectionRevokedError("connection has been revoked")
        self._row = row
        refresh_token: str | None = None
        if row.secret_enc:
            secret = self._box.decrypt_json(row.secret_enc)
            if isinstance(secret, dict):
                value = secret.get(REFRESH_TOKEN_KEY)
                refresh_token = value if isinstance(value, str) and value else None
        client: OAuthClient | None = None
        if row.provider_app_id is not None:
            app = await self._session.scalar(
                select(ProviderApp).where(
                    ProviderApp.id == row.provider_app_id,
                    ProviderApp.org_id == org_id,
                )
            )
            if app is not None:
                client = OAuthClient(
                    client_id=app.client_id,
                    client_secret=self._box.decrypt(app.client_secret_enc),
                )
        return RefreshState(
            status=row.status,
            access_token=(
                self._box.decrypt(row.access_token_enc)
                if row.access_token_enc
                else None
            ),
            expires_at=row.expires_at,
            refresh_token=refresh_token,
            client=client,
        )

    async def save(
        self,
        *,
        access_token: str,
        expires_at: datetime,
        refresh_token: str | None,
        scopes_granted: tuple[str, ...] | None,
    ) -> None:
        row = self._loaded()
        row.access_token_enc = self._box.encrypt(access_token)
        row.expires_at = expires_at
        if refresh_token:  # rotated
            row.secret_enc = self._box.encrypt_json({REFRESH_TOKEN_KEY: refresh_token})
        if scopes_granted:
            row.scopes_granted = list(scopes_granted)
        await self._session.commit()

    async def mark_error(self, message: str, *, drop_tokens: bool) -> None:
        """Flag the connection; with ``drop_tokens`` also wipe its (dead)
        tokens, so later calls fail fast without asking the provider."""
        row = self._loaded()
        row.status = ConnectionStatus.ERROR
        row.last_error = message
        if drop_tokens:
            row.secret_enc = None
            row.access_token_enc = None
            row.expires_at = None
        await self._session.commit()

    def _loaded(self) -> Connection:
        if self._row is None:
            raise RuntimeError("load() must be called first")
        return self._row
