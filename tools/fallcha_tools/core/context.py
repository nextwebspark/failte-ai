"""Build a :class:`ConnectionContext` for an authenticated connection key."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx

from fallcha_tools.core.crypto import SecretBox
from fallcha_tools.core.db import Database
from fallcha_tools.core.models import AuthMode
from fallcha_tools.core.oauth import ConnectionTokens, OAuthTokenManager
from fallcha_tools.core.provider import (
    AccessToken,
    ConnectionContext,
    ProviderRegistry,
)
from fallcha_tools.core.repositories import ConnectionRepository


@dataclass(frozen=True, slots=True)
class ContextLoader:
    """Decrypts one connection's secrets into a per-call context.

    OAuth2 connections also get ``ctx.oauth``, which refreshes the access
    token on demand through ``tokens``.
    """

    db: Database
    box: SecretBox
    http: httpx.AsyncClient
    registry: ProviderRegistry
    tokens: OAuthTokenManager

    async def load(
        self, org_id: int, connection_id: uuid.UUID, provider_id: str
    ) -> ConnectionContext:
        """Raises the repository's ``ToolsError`` subclasses if not usable."""
        async with self.db.session() as session:
            loaded = await ConnectionRepository(session, self.box).load_secrets(
                org_id, connection_id
            )
        info = loaded.info
        oauth: ConnectionTokens | None = None
        spec = self.registry.get(provider_id).oauth
        if info.auth_mode == AuthMode.OAUTH2 and spec is not None:
            oauth = ConnectionTokens(
                manager=self.tokens,
                org_id=org_id,
                connection_id=connection_id,
                spec=spec,
                loaded=(
                    AccessToken(loaded.access_token, info.expires_at)
                    if loaded.access_token and info.expires_at is not None
                    else None
                ),
            )
        return ConnectionContext(
            org_id=org_id,
            connection_id=connection_id,
            provider=provider_id,
            auth_mode=info.auth_mode,
            # Tool code never sees a refresh token: only ``oauth`` uses it.
            secret={} if oauth is not None else loaded.secret,
            access_token=loaded.access_token,
            http=self.http,
            config=info.config,
            account_label=info.account_label,
            scopes_granted=info.scopes_granted,
            oauth=oauth,
            db=self.db,
        )
