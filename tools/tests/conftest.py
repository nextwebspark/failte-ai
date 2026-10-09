from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from fallcha_tools.app import create_app
from fallcha_tools.config import Settings
from fallcha_tools.core.crypto import generate_key
from fallcha_tools.core.provider import ProviderRegistry
from tests.echo_provider import EchoProvider

TOOLS_DIR = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get(
    "TOOLS_TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/fallcha_tools_test",
)
INTERNAL_SECRET = "test-internal-secret-0123456789"

# Tests truncate and migrate up/down: refuse anything but a *_test database.
assert (make_url(TEST_DATABASE_URL).database or "").endswith("_test"), (
    "TOOLS_TEST_DATABASE_URL must point at a database whose name ends in _test"
)


def alembic_config() -> Config:
    cfg = Config(str(TOOLS_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _migrated() -> Iterator[None]:
    command.upgrade(alembic_config(), "head")
    yield


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(TEST_DATABASE_URL)
    yield eng
    await eng.dispose()


@pytest.fixture(autouse=True)
async def _clean_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE fallcha_tools.connection_keys, fallcha_tools.connections,"
                " fallcha_tools.oauth_states, fallcha_tools.provider_apps CASCADE"
            )
        )


@pytest.fixture
def settings() -> Settings:
    values: dict[str, Any] = {
        "DATABASE_URL": TEST_DATABASE_URL,
        "TOOLS_ENCRYPTION_KEYS": generate_key(),
        "TOOLS_INTERNAL_SECRET": INTERNAL_SECRET,
        "TOOLS_PUBLIC_BASE_URL": "http://tools.test",
        "LOG_LEVEL": "WARNING",
    }
    return Settings(**values)


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    registry = ProviderRegistry([EchoProvider(), EchoProvider(id="echo-b")])
    application = create_app(settings, registry)
    # The MCP session managers hold anyio cancel scopes that must be exited by
    # the task that entered them; pytest-asyncio may tear fixtures down from a
    # different task, so the lifespan runs in its own task.
    started, stop = asyncio.Event(), asyncio.Event()

    async def run_lifespan() -> None:
        async with application.router.lifespan_context(application):
            started.set()
            await stop.wait()

    task = asyncio.create_task(run_lifespan())
    ready = asyncio.create_task(started.wait())
    await asyncio.wait([task, ready], return_when=asyncio.FIRST_COMPLETED)
    if task.done():
        ready.cancel()
        task.result()  # surface startup failures
    yield application
    stop.set()
    await task


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://tools") as c:
        yield c


def internal_headers(org_id: int = 1, user_id: int = 10) -> dict[str, str]:
    return {
        "X-Internal-Secret": INTERNAL_SECRET,
        "X-Org-Id": str(org_id),
        "X-User-Id": str(user_id),
    }


async def create_echo_connection(
    client: httpx.AsyncClient,
    *,
    org_id: int = 1,
    provider: str = "echo",
    api_key: str = "good",
) -> str:
    response = await client.post(
        "/internal/connections",
        headers=internal_headers(org_id),
        json={
            "provider": provider,
            "auth_mode": "api_key",
            "secret": {"api_key": api_key},
        },
    )
    assert response.status_code == 201, response.text
    connection_id: str = response.json()["id"]
    return connection_id


async def issue_key(
    client: httpx.AsyncClient, connection_id: str, *, org_id: int = 1
) -> str:
    response = await client.post(
        f"/internal/connections/{connection_id}/keys",
        headers=internal_headers(org_id),
        json={"fallcha_credential_uuid": "cred-123"},
    )
    assert response.status_code == 201, response.text
    key: str = response.json()["key"]
    return key
