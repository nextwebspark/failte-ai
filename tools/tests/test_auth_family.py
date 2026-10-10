"""Auth families: shared OAuth clients, reused service-account keys, login hints."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import command
from fallcha_tools.config import Settings
from fallcha_tools.core.provider import ProviderRegistry
from fallcha_tools.providers.google_calendar import GoogleCalendarProvider
from fallcha_tools.providers.google_sheets import GoogleSheetsProvider
from tests.conftest import alembic_config, internal_headers
from tests.echo_provider import EchoProvider
from tests.google_fakes import (
    BOOKING_KEY,
    SA_EMAIL,
    calendar_config,
    service_account_key,
)
from tests.sheets_fakes import sheets_config


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "public_base_url": "https://tools.test",
            "ui_return_url": "https://app.test/integrations",
        }
    )


@pytest.fixture
def registry() -> ProviderRegistry:
    return ProviderRegistry(
        [
            GoogleCalendarProvider(booking_id_key=BOOKING_KEY),
            GoogleSheetsProvider(),
            EchoProvider(),
            EchoProvider(id="echo-b"),
        ]
    )


async def calendar_sa(client: httpx.AsyncClient, org_id: int = 1) -> str:
    response = await client.post(
        "/internal/connections",
        headers=internal_headers(org_id),
        json={
            "provider": "google-calendar",
            "auth_mode": "service_account",
            "secret": service_account_key(),
            "config": calendar_config(),
        },
    )
    assert response.status_code == 201, response.text
    connection_id: str = response.json()["id"]
    return connection_id


async def reuse(
    client: httpx.AsyncClient,
    source: str,
    *,
    org_id: int = 1,
    provider: str = "google-sheets",
    auth_mode: str = "service_account",
    **extra: Any,
) -> httpx.Response:
    return await client.post(
        "/internal/connections",
        headers=internal_headers(org_id),
        json={
            "provider": provider,
            "auth_mode": auth_mode,
            "reuse_secret_from": source,
            "config": sheets_config() if provider == "google-sheets" else {},
            **extra,
        },
    )


async def test_catalog_shows_family_and_tool_summaries(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/internal/catalog", headers=internal_headers())
    providers = {p["id"]: p for p in response.json()["providers"]}
    assert providers["google-calendar"]["auth_family"] == "google"
    assert providers["google-sheets"]["auth_family"] == "google"
    assert providers["echo"]["auth_family"] is None
    assert providers["google-sheets"]["share_hint"] == "the spreadsheet"
    summaries = {t["name"]: t["summary"] for t in providers["google-calendar"]["tools"]}
    assert summaries["check_appointment_availability"] == "Check free appointment slots"
    # The agent still gets the full instructions.
    tool = providers["google-calendar"]["tools"][0]
    assert len(tool["description"]) > len(tool["summary"])
    assert providers["google-calendar"]["oauth"]["optional_scopes"] == []


async def test_reuse_service_account_across_the_family(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    source = await calendar_sa(client)
    created = await reuse(client, source)
    assert created.status_code == 201, created.text
    assert created.json()["account_label"] == SA_EMAIL
    assert "secret" not in created.text and "private_key" not in created.text
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT id, secret_enc FROM fallcha_tools.connections")
            )
        ).all()
    # Copied server-side (each connection keeps its own ciphertext).
    assert len(rows) == 2 and all(r.secret_enc for r in rows)


async def test_reuse_rejections(client: httpx.AsyncClient, engine: AsyncEngine) -> None:
    source = await calendar_sa(client, org_id=1)
    # Another org's connection does not exist for this org.
    assert (await reuse(client, source, org_id=2)).status_code == 404
    assert (await reuse(client, str(uuid.uuid4()))).status_code == 404
    # Not with a secret too, and never an OAuth grant.
    both = await reuse(client, source, secret=service_account_key())
    assert both.status_code == 422
    oauth = await reuse(client, source, auth_mode="oauth2")
    assert oauth.status_code == 422
    # Another family (echo and echo-b are separate families).
    echo = await client.post(
        "/internal/connections",
        headers=internal_headers(),
        json={"provider": "echo", "auth_mode": "api_key", "secret": {"api_key": "k"}},
    )
    other_family = await reuse(
        client, echo.json()["id"], provider="echo-b", auth_mode="api_key"
    )
    assert other_family.status_code == 422
    assert "same provider family" in other_family.json()["detail"]
    same_family = await reuse(
        client, echo.json()["id"], provider="echo", auth_mode="api_key"
    )
    assert same_family.status_code == 201
    # Mismatched auth mode.
    mismatch = await reuse(client, echo.json()["id"], provider="echo-b")
    assert mismatch.status_code == 422
    # A connection in error, or revoked, cannot lend its secret.
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE fallcha_tools.connections SET status = 'error' WHERE id = :i"),
            {"i": source},
        )
    assert (await reuse(client, source)).status_code == 409
    await client.delete(f"/internal/connections/{source}", headers=internal_headers())
    assert (await reuse(client, source)).status_code == 409


async def test_one_oauth_client_serves_the_family(client: httpx.AsyncClient) -> None:
    saved = await client.post(
        "/internal/provider-apps",
        headers=internal_headers(),
        json={
            "provider": "google-calendar",
            "client_id": "1234.apps.googleusercontent.com",
            "client_secret": "GOCSPX-x",
        },
    )
    assert saved.status_code == 201 and saved.json()["provider"] == "google"
    started = await client.post(
        "/internal/oauth/start",
        headers=internal_headers(),
        json={
            "provider": "google-sheets",
            "provider_app_id": saved.json()["id"],
            "login_hint": "alice@acme.test",
        },
    )
    assert started.status_code == 200, started.text
    query = parse_qs(urlsplit(started.json()["authorization_url"]).query)
    assert query["client_id"] == ["1234.apps.googleusercontent.com"]
    assert "https://www.googleapis.com/auth/spreadsheets" in query["scope"][0].split()
    assert query["login_hint"] == ["alice@acme.test"]
    assert query["include_granted_scopes"] == ["true"]
    assert started.json()["redirect_uri"].endswith("/oauth/google-sheets/callback")

    bad_hint = await client.post(
        "/internal/oauth/start",
        headers=internal_headers(),
        json={
            "provider": "google-sheets",
            "provider_app_id": saved.json()["id"],
            "login_hint": "not an email",
        },
    )
    assert bad_hint.status_code == 422
    no_hint = await client.post(
        "/internal/oauth/start",
        headers=internal_headers(),
        json={"provider": "google-calendar", "provider_app_id": saved.json()["id"]},
    )
    assert "login_hint" not in no_hint.json()["authorization_url"]


def test_migration_moves_provider_apps_to_their_family() -> None:
    from tests.conftest import TEST_DATABASE_URL

    async def run(sql: str) -> list[Any]:
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(TEST_DATABASE_URL)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(sql))
                return list(result.all()) if result.returns_rows else []
        finally:
            await engine.dispose()

    cfg = alembic_config()
    command.downgrade(cfg, "0004")
    try:
        asyncio.run(
            run(
                "INSERT INTO fallcha_tools.provider_apps (id, org_id, provider,"
                " client_id, client_secret_enc) VALUES"
                f" ('{uuid.uuid4()}', 1, 'google-calendar', 'c', 'x'),"
                f" ('{uuid.uuid4()}', 1, 'other', 'c', 'x')"
            )
        )
        command.upgrade(cfg, "head")
        rows = asyncio.run(
            run("SELECT provider FROM fallcha_tools.provider_apps ORDER BY provider")
        )
        assert [r.provider for r in rows] == ["google", "other"]
        command.downgrade(cfg, "0004")
        rows = asyncio.run(
            run("SELECT provider FROM fallcha_tools.provider_apps ORDER BY provider")
        )
        assert [r.provider for r in rows] == ["google-calendar", "other"]
    finally:
        command.upgrade(cfg, "head")
        asyncio.run(run("DELETE FROM fallcha_tools.provider_apps"))
