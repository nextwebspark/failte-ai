"""The platform OAuth client (``TOOLS_GOOGLE_CLIENT_ID``): synced at startup,
offered to every workspace next to its own clients, never deletable, and
still serving its connections after it is rotated, replaced or unset."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx
from fastapi import FastAPI
from pydantic import SecretStr, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from fallcha_tools.app import create_app
from fallcha_tools.config import Settings
from fallcha_tools.core.container import AppServices
from fallcha_tools.core.crypto import SecretBox, generate_key
from fallcha_tools.core.oauth import OAuthReconnectRequired, OAuthTokenManager
from fallcha_tools.core.platform_apps import PlatformClient, sync_platform_client
from fallcha_tools.core.provider import AccessToken, ProviderRegistry
from fallcha_tools.core.repositories import platform_app_id
from fallcha_tools.providers import platform_client
from fallcha_tools.providers.google_calendar import GoogleCalendarProvider
from fallcha_tools.providers.google_calendar.credentials import TokenCache
from fallcha_tools.providers.google_calendar.provider import (
    GOOGLE_OAUTH,
    GOOGLE_USERINFO_URL,
)
from fallcha_tools.providers.google_sheets import GoogleSheetsProvider
from tests.conftest import INTERNAL_SECRET, TEST_DATABASE_URL, internal_headers
from tests.echo_provider import EchoProvider
from tests.google_fakes import BOOKING_KEY, FakeGoogle, form_body
from tests.test_oauth import (
    ACCESS_TOKEN,
    EMAIL,
    GRANTED,
    PUBLIC_BASE,
    REFRESH_TOKEN,
    UI_RETURN,
    callback,
    confirm,
    create_app_row,
    expire_access_token,
    refreshed,
    row,
)

PLATFORM_ID = "999-platform.apps.googleusercontent.com"
PLATFORM_SECRET = "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eak"
PLATFORM_APP_ID = platform_app_id("google", PLATFORM_ID)
NEW_PLATFORM_ID = "777-replacement.apps.googleusercontent.com"
NEW_PLATFORM_SECRET = "GOCSPX-replacement-secret"


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "public_base_url": PUBLIC_BASE,
            "ui_return_url": UI_RETURN,
            "google_client_id": PLATFORM_ID,
            "google_client_secret": SecretStr(PLATFORM_SECRET),
        }
    )


@pytest.fixture
def registry() -> ProviderRegistry:
    return ProviderRegistry(
        [
            GoogleCalendarProvider(
                booking_id_key=BOOKING_KEY, token_cache=TokenCache()
            ),
            GoogleSheetsProvider(),
            EchoProvider(),
        ]
    )


@pytest.fixture
def google() -> Iterator[FakeGoogle]:
    with respx.mock(assert_all_called=False) as router:
        fake = FakeGoogle(router)
        fake.token.mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": ACCESS_TOKEN,
                    "refresh_token": REFRESH_TOKEN,
                    "expires_in": 3599,
                    "scope": GRANTED,
                    "token_type": "Bearer",
                },
            )
        )
        router.get(GOOGLE_USERINFO_URL).respond(json={"sub": "1", "email": EMAIL})
        yield fake


def services(app: FastAPI) -> AppServices:
    svc: AppServices = app.state.services
    return svc


@asynccontextmanager
async def restarted(
    settings: Settings, registry: ProviderRegistry
) -> AsyncIterator[tuple[AppServices, httpx.AsyncClient]]:
    """The service restarted with other settings (startup sync included)."""
    application = create_app(settings, registry)
    svc = services(application)
    configured = platform_client(settings)
    if configured is not None:
        await sync_platform_client(svc.db, svc.box, configured)
    transport = httpx.ASGITransport(app=application)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://tools") as c:
            yield svc, c
    finally:
        await svc.http.aclose()
        await svc.db.dispose()


async def platform_rows(engine: AsyncEngine) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT * FROM fallcha_tools.provider_apps"
                " WHERE org_id IS NULL ORDER BY created_at"
            )
        )
        return [dict(r) for r in result.mappings()]


async def listed(client: httpx.AsyncClient, org_id: int = 1) -> list[dict[str, Any]]:
    response = await client.get(
        "/internal/provider-apps", headers=internal_headers(org_id)
    )
    assert response.status_code == 200, response.text
    assert PLATFORM_SECRET not in response.text
    apps: list[dict[str, Any]] = response.json()["provider_apps"]
    return apps


async def start(
    client: httpx.AsyncClient,
    app_id: uuid.UUID | str,
    *,
    org_id: int = 1,
    provider: str = "google-calendar",
) -> httpx.Response:
    return await client.post(
        "/internal/oauth/start",
        headers=internal_headers(org_id, user_id=42),
        json={"provider": provider, "provider_app_id": str(app_id)},
    )


async def started(
    client: httpx.AsyncClient, app_id: uuid.UUID | str, **extra: Any
) -> dict[str, str]:
    response = await start(client, app_id, **extra)
    assert response.status_code == 200, response.text
    assert PLATFORM_SECRET not in response.text
    query = urlsplit(response.json()["authorization_url"]).query
    params = {k: v[0] for k, v in parse_qs(query).items()}
    params["browser_nonce"] = response.json()["browser_nonce"]
    return params


async def finish(
    client: httpx.AsyncClient, params: dict[str, str], *, org_id: int = 1
) -> str:
    """Callback + confirm; returns the ACTIVE connection's id."""
    result = await callback(client, state=params["state"], code="auth-code-1")
    assert result["integration_result"] == "success", result
    connection_id = result["connection_id"]
    confirmed = await confirm(
        client, connection_id, params["browser_nonce"], org_id=org_id
    )
    assert confirmed.status_code == 200, confirmed.text
    return connection_id


async def refresh(
    svc: AppServices, connection_id: str, *, org_id: int = 1
) -> AccessToken:
    manager = OAuthTokenManager(db=svc.db, box=svc.box, http=svc.http)
    return await manager.access_token(org_id, uuid.UUID(connection_id), GOOGLE_OAUTH)


# --- settings ----------------------------------------------------------------


def base_settings(**extra: str) -> Settings:
    values: dict[str, Any] = {
        "DATABASE_URL": TEST_DATABASE_URL,
        "TOOLS_ENCRYPTION_KEYS": generate_key(),
        "TOOLS_INTERNAL_SECRET": INTERNAL_SECRET,
        **extra,
    }
    return Settings(**values)


@pytest.fixture
def _no_google_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("TOOLS_GOOGLE_CLIENT_ID", "TOOLS_GOOGLE_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.usefixtures("_no_google_env")
@pytest.mark.parametrize(
    "half",
    [
        {"TOOLS_GOOGLE_CLIENT_ID": PLATFORM_ID},
        {"TOOLS_GOOGLE_CLIENT_SECRET": PLATFORM_SECRET},
        {"TOOLS_GOOGLE_CLIENT_ID": PLATFORM_ID, "TOOLS_GOOGLE_CLIENT_SECRET": " "},
    ],
)
def test_google_client_needs_both_halves(half: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="both") as raised:
        base_settings(**half)
    assert PLATFORM_SECRET not in str(raised.value)


def test_settings_errors_never_echo_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pydantic would print a truncated dict of every env value it read."""
    secret = "GOCSPX-" + "s3cr3t" * 8
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("TOOLS_ENCRYPTION_KEYS", generate_key())
    monkeypatch.setenv("TOOLS_INTERNAL_SECRET", INTERNAL_SECRET)
    monkeypatch.delenv("TOOLS_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.setenv("TOOLS_GOOGLE_CLIENT_SECRET", secret)

    with pytest.raises(ValidationError, match="both") as raised:
        Settings()
    assert "s3cr3t" not in str(raised.value)
    assert INTERNAL_SECRET not in str(raised.value)


@pytest.mark.usefixtures("_no_google_env")
def test_google_client_settings() -> None:
    blank = base_settings(TOOLS_GOOGLE_CLIENT_ID="", TOOLS_GOOGLE_CLIENT_SECRET="")
    assert blank.google_client_id is None and blank.google_client_secret is None
    assert platform_client(blank) is None

    configured = base_settings(
        TOOLS_GOOGLE_CLIENT_ID=f" {PLATFORM_ID}\n",
        TOOLS_GOOGLE_CLIENT_SECRET=f"{PLATFORM_SECRET}\n",
    )
    client = platform_client(configured)
    assert client == PlatformClient("google", PLATFORM_ID, PLATFORM_SECRET)
    assert client.app_id == PLATFORM_APP_ID
    assert PLATFORM_SECRET not in repr(configured) + repr(client)

    with pytest.raises(ValidationError, match="printable ASCII"):
        base_settings(
            TOOLS_GOOGLE_CLIENT_ID="has space", TOOLS_GOOGLE_CLIENT_SECRET="s"
        )


# --- startup sync ------------------------------------------------------------


async def test_startup_syncs_the_platform_app(
    app: FastAPI, engine: AsyncEngine
) -> None:
    [stored] = await platform_rows(engine)
    assert stored["id"] == PLATFORM_APP_ID
    assert (stored["provider"], stored["client_id"]) == ("google", PLATFORM_ID)
    assert stored["created_by"] is None
    assert PLATFORM_SECRET not in stored["client_secret_enc"]
    assert services(app).box.decrypt(stored["client_secret_enc"]) == PLATFORM_SECRET


async def test_sync_is_idempotent_and_rotates_the_secret_in_place(
    app: FastAPI,
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    google: FakeGoogle,
) -> None:
    svc = services(app)
    connection_id = await finish(client, await started(client, PLATFORM_APP_ID))
    [before] = await platform_rows(engine)

    await sync_platform_client(
        svc.db, svc.box, PlatformClient("google", PLATFORM_ID, PLATFORM_SECRET)
    )
    [again] = await platform_rows(engine)
    assert (again["id"], again["created_at"]) == (before["id"], before["created_at"])

    await sync_platform_client(
        svc.db, svc.box, PlatformClient("google", PLATFORM_ID, "GOCSPX-rotated")
    )
    [rotated] = await platform_rows(engine)
    assert rotated["id"] == before["id"]
    assert rotated["created_at"] == before["created_at"]
    assert rotated["updated_at"] > before["updated_at"]
    assert svc.box.decrypt(rotated["client_secret_enc"]) == "GOCSPX-rotated"

    # The connection is still linked and refreshes with the new secret.
    assert (await row(engine, connection_id))["provider_app_id"] == PLATFORM_APP_ID
    await expire_access_token(engine, connection_id)
    google.token.mock(return_value=refreshed())
    assert (await refresh(svc, connection_id)).token == "ya29.refreshed"
    sent = form_body(google.token.calls.last.request)
    assert (sent["client_id"], sent["client_secret"]) == (PLATFORM_ID, "GOCSPX-rotated")


# --- listing and tenant isolation ----------------------------------------------


async def test_every_org_sees_the_platform_app_first_and_only_its_own(
    client: httpx.AsyncClient,
) -> None:
    own = (await create_app_row(client, org_id=1)).json()["id"]
    other = (await create_app_row(client, org_id=2)).json()["id"]

    apps = await listed(client, org_id=1)
    assert [(a["id"], a["managed"]) for a in apps] == [
        (str(PLATFORM_APP_ID), True),
        (own, False),
    ]
    assert apps[0]["provider"] == "google" and apps[0]["client_id"] == PLATFORM_ID
    assert [a["id"] for a in await listed(client, org_id=2)] == [
        str(PLATFORM_APP_ID),
        other,
    ]
    # Neither org can start a flow with, or delete, the other's client.
    assert (await start(client, other, org_id=1)).status_code == 404
    assert (await start(client, own, org_id=2)).status_code == 404
    path = f"/internal/provider-apps/{own}"
    assert (await client.delete(path, headers=internal_headers(2))).status_code == 404


async def test_platform_app_cannot_be_deleted(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    path = f"/internal/provider-apps/{PLATFORM_APP_ID}"
    for org_id in (1, 2):
        response = await client.delete(path, headers=internal_headers(org_id))
        assert response.status_code == 409
        assert "managed by the platform" in response.json()["detail"]
    assert len(await platform_rows(engine)) == 1


async def test_refresh_never_uses_another_orgs_client(
    app: FastAPI, client: httpx.AsyncClient, engine: AsyncEngine, google: FakeGoogle
) -> None:
    connection_id = await finish(client, await started(client, PLATFORM_APP_ID))
    foreign = (await create_app_row(client, org_id=2)).json()["id"]
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE fallcha_tools.connections SET provider_app_id = :app,"
                " expires_at = now() WHERE id = :id"
            ),
            {"app": foreign, "id": connection_id},
        )
    exchanges = google.token.call_count
    with pytest.raises(OAuthReconnectRequired, match="was removed"):
        await refresh(services(app), connection_id)
    assert google.token.call_count == exchanges


# --- connecting --------------------------------------------------------------


async def test_connect_and_refresh_with_the_platform_client(
    app: FastAPI, client: httpx.AsyncClient, engine: AsyncEngine, google: FakeGoogle
) -> None:
    params = await started(client, PLATFORM_APP_ID)
    assert params["client_id"] == PLATFORM_ID
    assert params["redirect_uri"] == f"{PUBLIC_BASE}/oauth/google-calendar/callback"
    connection_id = await finish(client, params)

    exchanged = form_body(google.token.calls.last.request)
    assert exchanged["grant_type"] == "authorization_code"
    assert (exchanged["client_id"], exchanged["client_secret"]) == (
        PLATFORM_ID,
        PLATFORM_SECRET,
    )
    stored = await row(engine, connection_id)
    assert (stored["org_id"], stored["provider_app_id"]) == (1, PLATFORM_APP_ID)
    assert stored["account_label"] == EMAIL

    await expire_access_token(engine, connection_id)
    google.token.mock(return_value=refreshed())
    assert (await refresh(services(app), connection_id)).token == "ya29.refreshed"
    assert form_body(google.token.calls.last.request) == {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": PLATFORM_ID,
        "client_secret": PLATFORM_SECRET,
    }


async def test_platform_client_serves_the_whole_family(
    client: httpx.AsyncClient,
) -> None:
    params = await started(client, PLATFORM_APP_ID, provider="google-sheets")
    assert params["client_id"] == PLATFORM_ID
    assert params["redirect_uri"] == f"{PUBLIC_BASE}/oauth/google-sheets/callback"
    # Echo has no OAuth: the Google client is no use there.
    assert (await start(client, PLATFORM_APP_ID, provider="echo")).status_code == 422


# --- replaced or unset -------------------------------------------------------


async def test_new_client_id_adds_a_row_and_old_connections_keep_refreshing(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    settings: Settings,
    registry: ProviderRegistry,
    google: FakeGoogle,
) -> None:
    connection_id = await finish(client, await started(client, PLATFORM_APP_ID))
    in_flight = await started(client, PLATFORM_APP_ID)
    replaced = settings.model_copy(
        update={
            "google_client_id": NEW_PLATFORM_ID,
            "google_client_secret": SecretStr(NEW_PLATFORM_SECRET),
        }
    )
    new_app_id = platform_app_id("google", NEW_PLATFORM_ID)
    async with restarted(replaced, registry) as (svc, c):
        assert [r["id"] for r in await platform_rows(engine)] == [
            PLATFORM_APP_ID,
            new_app_id,
        ]
        # Only the current client is offered...
        assert [a["id"] for a in await listed(c)] == [str(new_app_id)]
        assert (await start(c, PLATFORM_APP_ID)).status_code == 404
        old_path = f"/internal/provider-apps/{PLATFORM_APP_ID}"
        assert (await c.delete(old_path, headers=internal_headers())).status_code == 404
        assert (await started(c, new_app_id))["client_id"] == NEW_PLATFORM_ID

        # ...but a flow started with the old one completes with it,
        late = await finish(c, in_flight)
        assert form_body(google.token.calls.last.request)["client_id"] == PLATFORM_ID
        assert (await row(engine, late))["provider_app_id"] == PLATFORM_APP_ID

        # and its connections refresh with it (their tokens belong to it).
        await expire_access_token(engine, connection_id)
        google.token.mock(return_value=refreshed())
        assert (await refresh(svc, connection_id)).token == "ya29.refreshed"
        sent = form_body(google.token.calls.last.request)
        assert (sent["client_id"], sent["client_secret"]) == (
            PLATFORM_ID,
            PLATFORM_SECRET,
        )


async def test_unset_platform_client_is_hidden_but_still_refreshes(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    settings: Settings,
    registry: ProviderRegistry,
    google: FakeGoogle,
) -> None:
    connection_id = await finish(client, await started(client, PLATFORM_APP_ID))
    unset = settings.model_copy(
        update={"google_client_id": None, "google_client_secret": None}
    )
    async with restarted(unset, registry) as (svc, c):
        assert await listed(c) == []
        assert (await start(c, PLATFORM_APP_ID)).status_code == 404
        path = f"/internal/provider-apps/{PLATFORM_APP_ID}"
        assert (await c.delete(path, headers=internal_headers())).status_code == 404
        assert len(await platform_rows(engine)) == 1

        await expire_access_token(engine, connection_id)
        google.token.mock(return_value=refreshed())
        assert (await refresh(svc, connection_id)).token == "ya29.refreshed"
        assert form_body(google.token.calls.last.request)["client_id"] == PLATFORM_ID


# --- recovery after a bad platform secret, key rotation, scopes ---------------


async def test_restart_lets_connections_rejected_for_the_platform_client_retry(
    app: FastAPI,
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    google: FakeGoogle,
    settings: Settings,
    registry: ProviderRegistry,
) -> None:
    """A bad deployment secret must not force every workspace to reconnect."""
    platform_conn = await finish(client, await started(client, PLATFORM_APP_ID))
    own_app = (await create_app_row(client)).json()["id"]
    own_conn = await finish(client, await started(client, own_app))
    for connection_id in (platform_conn, own_conn):
        await expire_access_token(engine, connection_id)
    google.token.mock(
        return_value=httpx.Response(401, json={"error": "invalid_client"})
    )
    for connection_id in (platform_conn, own_conn):
        with pytest.raises(OAuthReconnectRequired, match="rejected the OAuth client"):
            await refresh(services(app), connection_id)
        assert (await row(engine, connection_id))["error_code"] == "client_rejected"

    google.token.mock(return_value=refreshed())
    async with restarted(settings, registry) as (svc, _):
        assert (await refresh(svc, platform_conn)).token == "ya29.refreshed"
        # A workspace's own client is its own business: still flagged.
        with pytest.raises(OAuthReconnectRequired, match="rejected the OAuth client"):
            await refresh(svc, own_conn)
    stored = await row(engine, platform_conn)
    assert (stored["status"], stored["error_code"]) == ("active", None)
    assert (await row(engine, own_conn))["error_code"] == "client_rejected"


async def test_sync_reencrypts_replaced_platform_clients_under_the_primary_key(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    settings: Settings,
    registry: ProviderRegistry,
) -> None:
    old_key = settings.encryption_keys[0]
    new_key = generate_key()
    replaced = settings.model_copy(
        update={
            "google_client_id": NEW_PLATFORM_ID,
            "google_client_secret": SecretStr(NEW_PLATFORM_SECRET),
            "encryption_keys_raw": SecretStr(f"{new_key},{old_key}"),
        }
    )
    async with restarted(replaced, registry):
        pass

    new_only = SecretBox([new_key])
    secrets_by_id = {
        r["id"]: new_only.decrypt(r["client_secret_enc"])
        for r in await platform_rows(engine)
    }
    assert secrets_by_id == {
        PLATFORM_APP_ID: PLATFORM_SECRET,
        platform_app_id("google", NEW_PLATFORM_ID): NEW_PLATFORM_SECRET,
    }


async def test_connections_keep_only_their_providers_scopes(
    client: httpx.AsyncClient, engine: AsyncEngine, google: FakeGoogle
) -> None:
    """A token can carry scopes the same account granted the shared client for
    another integration or workspace; they are not this connection's."""
    params = await started(client, PLATFORM_APP_ID)
    assert params["include_granted_scopes"] == "false"
    google.token.mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": ACCESS_TOKEN,
                "refresh_token": REFRESH_TOKEN,
                "expires_in": 3599,
                "scope": f"{GRANTED} https://www.googleapis.com/auth/spreadsheets",
                "token_type": "Bearer",
            },
        )
    )
    connection_id = await finish(client, params)
    stored = await row(engine, connection_id)
    assert (
        "https://www.googleapis.com/auth/spreadsheets" not in stored["scopes_granted"]
    )
    assert "https://www.googleapis.com/auth/calendar.events" in stored["scopes_granted"]
