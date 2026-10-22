"""``DELETE /internal/org``: erase everything a workspace keeps here."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from fallcha_tools.core.sync import SyncRunner
from fallcha_tools.providers.google_common.scopes import GOOGLE_REVOKE_URL
from tests import test_oauth
from tests.conftest import INTERNAL_SECRET, create_echo_connection, issue_key
from tests.google_fakes import FakeGoogle
from tests.test_oauth import REFRESH_TOKEN, connect, services

# The OAuth tests' Google-backed app, reused as fixtures.
settings = test_oauth.settings
registry = test_oauth.registry
google = test_oauth.google

TABLES = ("connections", "connection_keys", "oauth_states", "provider_apps")


def erase_headers(org_id: int) -> dict[str, str]:
    return {"X-Internal-Secret": INTERNAL_SECRET, "X-Org-Id": str(org_id)}


async def counts(engine: AsyncEngine, org_id: int) -> dict[str, int]:
    out: dict[str, int] = {}
    async with engine.connect() as conn:
        for table in TABLES:
            out[table] = (
                await conn.execute(
                    text(
                        f"SELECT count(*) FROM fallcha_tools.{table} WHERE org_id = :o"
                    ),
                    {"o": org_id},
                )
            ).scalar_one()
    return out


async def test_erase_org_deletes_only_that_org_and_revokes_grants(
    client: httpx.AsyncClient, engine: AsyncEngine, google: FakeGoogle
) -> None:
    revoke = google.router.post(GOOGLE_REVOKE_URL).respond(200)
    oauth_connection = await connect(client, org_id=1)
    echo = await create_echo_connection(client, org_id=1)
    await issue_key(client, echo, org_id=1)
    await issue_key(client, oauth_connection, org_id=1)
    other = await create_echo_connection(client, org_id=2)
    await issue_key(client, other, org_id=2)
    before_other = await counts(engine, 2)

    response = await client.delete("/internal/org", headers=erase_headers(1))

    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert body["connections"] == 2
    assert body["connection_keys"] == 2
    assert body["provider_apps"] == 1
    assert body["tokens_revoked"] == 1
    assert revoke.called
    assert f"token={REFRESH_TOKEN.replace('/', '%2F')}" in (
        revoke.calls.last.request.content.decode()
    )
    assert await counts(engine, 1) == dict.fromkeys(TABLES, 0)
    assert await counts(engine, 2) == before_other

    # Idempotent.
    again = await client.delete("/internal/org", headers=erase_headers(1))
    assert again.status_code == 200
    assert again.json()["connections"] == 0


async def test_unreachable_revocation_does_not_block_erasure(
    client: httpx.AsyncClient, engine: AsyncEngine, google: FakeGoogle
) -> None:
    google.router.post(GOOGLE_REVOKE_URL).mock(side_effect=httpx.ConnectError("down"))
    await connect(client, org_id=1)

    response = await client.delete("/internal/org", headers=erase_headers(1))

    assert response.status_code == 200
    assert response.json()["tokens_revoked"] == 0
    assert (await counts(engine, 1))["connections"] == 0


async def test_erase_org_requires_the_secret_and_an_org(
    client: httpx.AsyncClient,
) -> None:
    wrong = await client.delete(
        "/internal/org", headers={"X-Internal-Secret": "nope", "X-Org-Id": "1"}
    )
    assert wrong.status_code == 401
    missing = await client.delete(
        "/internal/org", headers={"X-Internal-Secret": INTERNAL_SECRET}
    )
    assert missing.status_code == 400


@pytest.mark.parametrize("org_id", [1])
async def test_cancel_org_stops_only_that_orgs_syncs(app: FastAPI, org_id: int) -> None:
    runner: SyncRunner = services(app).sync
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    forever = asyncio.Event()

    async def wait_forever() -> None:
        await forever.wait()

    runner._tasks[mine] = asyncio.create_task(wait_forever())
    runner._task_orgs[mine] = org_id
    runner._tasks[theirs] = asyncio.create_task(wait_forever())
    runner._task_orgs[theirs] = org_id + 1
    try:
        assert await runner.cancel_org(org_id) == 1
        assert runner._tasks[mine].cancelled()
        assert not runner._tasks[theirs].done()
    finally:
        forever.set()
        await asyncio.wait([runner._tasks[theirs]])
        runner._tasks.clear()
        runner._task_orgs.clear()


async def test_grants_of_the_shared_platform_client_are_not_revoked(
    client: httpx.AsyncClient, engine: AsyncEngine, google: FakeGoogle
) -> None:
    """Revoking at Google would revoke that account's grant to the shared
    client in every workspace; deleting the secret is enough for us."""
    revoke = google.router.post(GOOGLE_REVOKE_URL).respond(200)
    await connect(client, org_id=1)
    # Make the connection's OAuth client the platform client (no org).
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE fallcha_tools.provider_apps SET org_id = NULL"))

    response = await client.delete("/internal/org", headers=erase_headers(1))

    assert response.status_code == 200
    assert response.json()["tokens_revoked"] == 0
    assert not revoke.called
    assert (await counts(engine, 1))["connections"] == 0
    async with engine.connect() as conn:
        platform_apps = await conn.execute(
            text(
                "SELECT count(*) FROM fallcha_tools.provider_apps WHERE org_id IS NULL"
            )
        )
        assert platform_apps.scalar_one() == 1
