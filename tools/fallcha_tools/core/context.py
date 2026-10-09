"""Build a :class:`ConnectionContext` for an authenticated connection key."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx

from fallcha_tools.core.crypto import SecretBox
from fallcha_tools.core.db import Database
from fallcha_tools.core.provider import ConnectionContext
from fallcha_tools.core.repositories import ConnectionRepository


@dataclass(frozen=True, slots=True)
class ContextLoader:
    """Decrypts one connection's secrets into a per-call context."""

    db: Database
    box: SecretBox
    http: httpx.AsyncClient

    async def load(
        self, org_id: int, connection_id: uuid.UUID, provider_id: str
    ) -> ConnectionContext:
        """Raises the repository's ``ToolsError`` subclasses if not usable."""
        async with self.db.session() as session:
            loaded = await ConnectionRepository(session, self.box).load_secrets(
                org_id, connection_id
            )
        return ConnectionContext(
            org_id=org_id,
            connection_id=connection_id,
            provider=provider_id,
            auth_mode=loaded.info.auth_mode,
            secret=loaded.secret,
            access_token=loaded.access_token,
            http=self.http,
            config=loaded.info.config,
        )
