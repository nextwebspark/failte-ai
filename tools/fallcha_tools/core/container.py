"""Process-wide services and the FastAPI dependencies that hand them out."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, cast

import httpx
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from fallcha_tools.config import Settings
from fallcha_tools.core.context import ContextLoader
from fallcha_tools.core.crypto import SecretBox
from fallcha_tools.core.db import Database
from fallcha_tools.core.oauth import OAuthFlow
from fallcha_tools.core.provider import ProviderRegistry
from fallcha_tools.core.repositories import (
    ConnectionRepository,
    KeyRepository,
    ProviderAppRepository,
)
from fallcha_tools.core.sync import SyncRunner

if TYPE_CHECKING:  # mcp -> auth -> container would otherwise be circular
    from fallcha_tools.core.mcp import McpMounts


@dataclass(frozen=True, slots=True)
class AppServices:
    settings: Settings
    db: Database
    box: SecretBox
    http: httpx.AsyncClient
    registry: ProviderRegistry
    mcp: McpMounts
    contexts: ContextLoader
    oauth: OAuthFlow
    sync: SyncRunner


def get_services(request: Request) -> AppServices:
    return cast(AppServices, request.app.state.services)


ServicesDep = Annotated[AppServices, Depends(get_services)]


async def get_session(services: ServicesDep) -> AsyncIterator[AsyncSession]:
    async with services.db.session() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_connection_repository(
    session: SessionDep, services: ServicesDep
) -> ConnectionRepository:
    return ConnectionRepository(session, services.box)


def get_key_repository(session: SessionDep) -> KeyRepository:
    return KeyRepository(session)


def get_provider_app_repository(
    session: SessionDep, services: ServicesDep
) -> ProviderAppRepository:
    return ProviderAppRepository(session, services.box)


ConnectionRepoDep = Annotated[ConnectionRepository, Depends(get_connection_repository)]
KeyRepoDep = Annotated[KeyRepository, Depends(get_key_repository)]
ProviderAppRepoDep = Annotated[
    ProviderAppRepository, Depends(get_provider_app_repository)
]
