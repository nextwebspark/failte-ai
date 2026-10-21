"""Erase everything a workspace (a LightMove organization) keeps here.

Called by the LightMove API when it erases an organization (GDPR Art. 17).
In order: stop this process's running syncs of the org's connections, revoke
OAuth refresh tokens issued to the org's own OAuth clients at the provider
where it offers a revocation endpoint (never the shared platform client's:
that would revoke the account's grant in every workspace). Revocation is
best effort: an unreachable provider never blocks erasure, and the grant is
useless without the deleted client secret and connection anyway. Then
delete every row of the org in one transaction: connections (their keys,
sync status and imported catalogue go with them), connection keys, OAuth
states and the org's own OAuth clients. The platform OAuth client
(``org_id`` NULL) is never touched. Idempotent: a second call finds nothing.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import Result, delete, select

from fallcha_tools.core.crypto import DecryptionError, SecretBox
from fallcha_tools.core.db import Database
from fallcha_tools.core.errors import ToolsError
from fallcha_tools.core.models import (
    AuthMode,
    Connection,
    ConnectionKey,
    ConnectionSync,
    OAuthState,
    ProviderApp,
)
from fallcha_tools.core.provider import ProviderRegistry
from fallcha_tools.core.repositories import REFRESH_TOKEN_KEY
from fallcha_tools.core.sync import SyncRunner

REVOKE_TIMEOUT = httpx.Timeout(4.0, connect=2.0)
# Revocations run in parallel, so an org with many grants stays well within
# the API's timeout for the erasure call.
REVOKE_CONCURRENCY = 8


def _count(result: Result[Any]) -> int:
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


@dataclass(frozen=True, slots=True)
class OrgErasureResult:
    connections: int
    connection_keys: int
    oauth_states: int
    provider_apps: int
    syncs_stopped: int
    tokens_revoked: int


@dataclass(frozen=True, slots=True)
class OrgEraser:
    db: Database
    box: SecretBox
    http: httpx.AsyncClient
    registry: ProviderRegistry
    sync: SyncRunner

    async def erase(self, org_id: int) -> OrgErasureResult:
        syncs_stopped = await self.sync.cancel_org(org_id)
        tokens_revoked = await self._revoke_refresh_tokens(org_id)
        async with self.db.session() as session:
            # Explicit org filters everywhere (cascades would also do), so a
            # bug in one relationship can never reach another workspace.
            keys = await session.execute(
                delete(ConnectionKey).where(ConnectionKey.org_id == org_id)
            )
            await session.execute(
                delete(ConnectionSync).where(ConnectionSync.org_id == org_id)
            )
            states = await session.execute(
                delete(OAuthState).where(OAuthState.org_id == org_id)
            )
            # Imported catalogue rows cascade from their connection.
            connections = await session.execute(
                delete(Connection).where(Connection.org_id == org_id)
            )
            apps = await session.execute(
                delete(ProviderApp).where(ProviderApp.org_id == org_id)
            )
            await session.commit()
        result = OrgErasureResult(
            connections=_count(connections),
            connection_keys=_count(keys),
            oauth_states=_count(states),
            provider_apps=_count(apps),
            syncs_stopped=syncs_stopped,
            tokens_revoked=tokens_revoked,
        )
        logger.info("erased org {}: {}", org_id, result)
        return result

    async def _revoke_refresh_tokens(self, org_id: int) -> int:
        """Revoke the grants issued to the org's OWN OAuth clients.

        A grant issued to the shared platform client is not revoked: Google
        revokes the whole grant of that account to the client, which would
        break the same Google account's connections in other workspaces.
        Deleting the secret already makes such a grant unusable to us.
        """
        async with self.db.session() as session:
            rows = (
                await session.execute(
                    select(Connection.provider, Connection.secret_enc)
                    .join(ProviderApp, ProviderApp.id == Connection.provider_app_id)
                    .where(
                        Connection.org_id == org_id,
                        Connection.auth_mode == AuthMode.OAUTH2,
                        Connection.secret_enc.is_not(None),
                        ProviderApp.org_id == org_id,
                    )
                )
            ).all()
        limit = asyncio.Semaphore(REVOKE_CONCURRENCY)

        async def revoke(provider_id: str, secret_enc: str) -> bool:
            async with limit:
                return await self._revoke_one(org_id, provider_id, secret_enc)

        results = await asyncio.gather(
            *(revoke(provider_id, secret_enc) for provider_id, secret_enc in rows)
        )
        return sum(results)

    async def _revoke_one(self, org_id: int, provider_id: str, secret_enc: str) -> bool:
        try:
            spec = self.registry.get(provider_id).oauth
            secret = self.box.decrypt_json(secret_enc)
        except (ToolsError, DecryptionError):
            return False
        token = secret.get(REFRESH_TOKEN_KEY) if isinstance(secret, dict) else None
        url = spec.revocation_url if spec is not None else None
        if url is None or not isinstance(token, str):
            return False
        try:
            response = await self.http.post(
                url, data={"token": token}, timeout=REVOKE_TIMEOUT
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "token revocation for org {} ({}) failed: {}",
                org_id,
                provider_id,
                type(exc).__name__,
            )
            return False
        # 400 typically means the token was already revoked or expired.
        if response.status_code < 300 or response.status_code == 400:
            return True
        logger.warning(
            "token revocation for org {} ({}) answered {}",
            org_id,
            provider_id,
            response.status_code,
        )
        return False
