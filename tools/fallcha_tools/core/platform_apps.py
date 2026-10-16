"""The platform's own OAuth clients, offered to every workspace.

A deployment may configure one client of its own (e.g. the Google client it
signs users in with). :func:`sync_platform_client` stores it at startup as a
``provider_apps`` row with ``org_id`` NULL, under the auth family, so every
provider of that family can use it. Workspaces still bring their own clients.

A new secret for the same client id updates the row in place; a new client id
is a new row, while connections made with the old one keep refreshing with it
(Google ties refresh tokens to the client that issued them).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from loguru import logger

from fallcha_tools.core.crypto import SecretBox
from fallcha_tools.core.db import Database
from fallcha_tools.core.repositories import PlatformAppRepository, platform_app_id


@dataclass(frozen=True, slots=True)
class PlatformClient:
    family: str
    client_id: str
    client_secret: str = field(repr=False)

    @property
    def app_id(self) -> uuid.UUID:
        return platform_app_id(self.family, self.client_id)


async def sync_platform_client(
    db: Database, box: SecretBox, client: PlatformClient
) -> None:
    """Upsert the client's row. Safe to run on every start and replica."""
    async with db.session() as session:
        await PlatformAppRepository(session, box).upsert(
            family=client.family,
            client_id=client.client_id,
            client_secret=client.client_secret,
        )
    logger.info("platform {} OAuth client {} synced", client.family, client.app_id)
