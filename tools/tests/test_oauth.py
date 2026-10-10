"""Bring-your-own OAuth2: provider apps, authorization (state + PKCE),
callback, and lazy single-flight token refresh. Google is mocked with respx."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastmcp.exceptions import ToolError
from loguru import logger as loguru_logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from fallcha_tools.config import Settings
from fallcha_tools.core.access_log import RedactOAuthQuery
from fallcha_tools.core.container import AppServices
from fallcha_tools.core.crypto import SecretBox
from fallcha_tools.core.db import Database
from fallcha_tools.core.oauth import (
    OAuthReconnectRequired,
    OAuthTokenManager,
    code_challenge,
)
from fallcha_tools.core.provider import AccessToken, ProviderRegistry
from fallcha_tools.core.repositories import hash_browser_nonce, hash_oauth_state
from fallcha_tools.providers.google_calendar import GoogleCalendarProvider
from fallcha_tools.providers.google_calendar.client import (
    SHEETS_READONLY_SCOPE,
    Budget,
    GoogleClient,
)
from fallcha_tools.providers.google_calendar.credentials import (
    OAuthCredentials,
    TokenCache,
)
from fallcha_tools.providers.google_calendar.errors import GoogleApiError
from fallcha_tools.providers.google_calendar.provider import (
    GOOGLE_AUTHORIZE_URL,
    GOOGLE_OAUTH,
    GOOGLE_USERINFO_URL,
)
from tests.conftest import TEST_DATABASE_URL, internal_headers, issue_key
from tests.echo_provider import EchoProvider
from tests.google_fakes import (
    BOOKING_KEY,
    FakeGoogle,
    calendar_config,
    form_body,
)
from tests.test_mcp import mcp_client

PROVIDER = "google-calendar"
UI_RETURN = "https://app.fallcha.test/integrations?tab=connected"
PUBLIC_BASE = "https://tools.fallcha.test/tools"
REDIRECT_URI = f"{PUBLIC_BASE}/oauth/{PROVIDER}/callback"
CLIENT_ID = "1234-abc.apps.googleusercontent.com"
CLIENT_SECRET = "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k"
REFRESH_TOKEN = "1//refresh-token-must-never-leak"
ACCESS_TOKEN = "ya29.first-access-token"
EMAIL = "alice@acme.test"
GRANTED = (
    "openid https://www.googleapis.com/auth/userinfo.email "
    "https://www.googleapis.com/auth/calendar.events "
    "https://www.googleapis.com/auth/calendar.readonly"
)


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={"public_base_url": PUBLIC_BASE, "ui_return_url": UI_RETURN}
    )


@pytest.fixture
def registry() -> ProviderRegistry:
    return ProviderRegistry(
        [
            GoogleCalendarProvider(
                booking_id_key=BOOKING_KEY, token_cache=TokenCache()
            ),
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
        router.get(GOOGLE_USERINFO_URL, name="userinfo").respond(
            json={"sub": "1", "email": EMAIL, "email_verified": True}
        )
        yield fake


def services(app: FastAPI) -> AppServices:
    services: AppServices = app.state.services
    return services


async def create_app_row(
    client: httpx.AsyncClient, *, org_id: int = 1, provider: str = PROVIDER
) -> httpx.Response:
    return await client.post(
        "/internal/provider-apps",
        headers=internal_headers(org_id),
        json={
            "provider": provider,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )


async def provider_app(client: httpx.AsyncClient, *, org_id: int = 1) -> str:
    response = await create_app_row(client, org_id=org_id)
    assert response.status_code == 201, response.text
    app_id: str = response.json()["id"]
    return app_id


async def start(
    client: httpx.AsyncClient, app_id: str, *, org_id: int = 1, **extra: Any
) -> httpx.Response:
    return await client.post(
        "/internal/oauth/start",
        headers=internal_headers(org_id, user_id=42),
        json={"provider": PROVIDER, "provider_app_id": app_id, **extra},
    )


async def started_params(
    client: httpx.AsyncClient, *, org_id: int = 1, **extra: Any
) -> dict[str, str]:
    app_id = await provider_app(client, org_id=org_id)
    response = await start(client, app_id, org_id=org_id, **extra)
    assert response.status_code == 200, response.text
    url = urlsplit(response.json()["authorization_url"])
    params = {k: v[0] for k, v in parse_qs(url.query).items()}
    # Test-only extra: the nonce the API would put in the user's cookie.
    params["browser_nonce"] = response.json()["browser_nonce"]
    return params


async def callback(client: httpx.AsyncClient, **params: str) -> dict[str, str]:
    """Hit the callback; return the UI redirect's query (asserting its base)."""
    response = await client.get(f"/oauth/{PROVIDER}/callback", params=params)
    assert response.status_code == 302, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    location = response.headers["location"]
    assert location.startswith("https://app.fallcha.test/integrations?tab=connected&")
    for secret in (params.get("code"), params.get("state")):
        if secret:
            assert secret not in location
    query = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
    assert query.pop("tab") == "connected"  # the return URL's own query is kept
    return query


async def confirm(
    client: httpx.AsyncClient,
    connection_id: str,
    nonce: str,
    *,
    org_id: int = 1,
    user_id: int = 42,
) -> httpx.Response:
    return await client.post(
        f"/internal/connections/{connection_id}/confirm",
        headers=internal_headers(org_id, user_id=user_id),
        json={"browser_nonce": nonce},
    )


async def connect_pending(
    client: httpx.AsyncClient, *, org_id: int = 1
) -> tuple[str, str]:
    """A PENDING connection id and the nonce that confirms it."""
    params = await started_params(client, org_id=org_id)
    result = await callback(client, state=params["state"], code="auth-code-1")
    assert result["integration_result"] == "success", result
    return result["connection_id"], params["browser_nonce"]


async def connect(client: httpx.AsyncClient, *, org_id: int = 1) -> str:
    """A confirmed (ACTIVE) OAuth connection."""
    connection_id, nonce = await connect_pending(client, org_id=org_id)
    confirmed = await confirm(client, connection_id, nonce, org_id=org_id)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "active"
    return connection_id


async def row(engine: AsyncEngine, connection_id: str) -> dict[str, Any]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT * FROM fallcha_tools.connections WHERE id = :id"),
            {"id": connection_id},
        )
        return dict(result.mappings().one())


def box(app: FastAPI) -> SecretBox:
    return services(app).box


async def expire_access_token(engine: AsyncEngine, connection_id: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE fallcha_tools.connections"
                " SET expires_at = now() + interval '1 minute' WHERE id = :id"
            ),
            {"id": connection_id},
        )


# --- provider apps -----------------------------------------------------------


async def test_provider_app_secret_is_encrypted_and_never_returned(
    client: httpx.AsyncClient, engine: AsyncEngine, app: FastAPI
) -> None:
    created = await create_app_row(client)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["client_id"] == CLIENT_ID and body["provider"] == PROVIDER
    assert CLIENT_SECRET not in created.text

    listed = await client.get("/internal/provider-apps", headers=internal_headers())
    assert [a["id"] for a in listed.json()["provider_apps"]] == [body["id"]]
    assert CLIENT_SECRET not in listed.text

    async with engine.connect() as conn:
        stored = (
            await conn.execute(
                text("SELECT client_secret_enc FROM fallcha_tools.provider_apps")
            )
        ).scalar_one()
    assert CLIENT_SECRET not in stored
    assert box(app).decrypt(stored) == CLIENT_SECRET


async def test_provider_apps_are_org_scoped(client: httpx.AsyncClient) -> None:
    app_id = await provider_app(client, org_id=1)
    other = await client.get("/internal/provider-apps", headers=internal_headers(2))
    assert other.json()["provider_apps"] == []
    deleted = await client.delete(
        f"/internal/provider-apps/{app_id}", headers=internal_headers(2)
    )
    assert deleted.status_code == 404
    # Org 2 cannot start a flow with org 1's client either.
    assert (await start(client, app_id, org_id=2)).status_code == 404

    deleted = await client.delete(
        f"/internal/provider-apps/{app_id}", headers=internal_headers(1)
    )
    assert deleted.status_code == 204


async def test_provider_app_validation(client: httpx.AsyncClient) -> None:
    # Echo has no OAuth support; unknown providers are 404.
    assert (await create_app_row(client, provider="echo")).status_code == 422
    assert (await create_app_row(client, provider="nope")).status_code == 404
    response = await client.post(
        "/internal/provider-apps",
        headers=internal_headers(),
        json={
            "provider": PROVIDER,
            "client_id": "has space",
            "client_secret": "x" * 600,
        },
    )
    assert response.status_code == 422
    assert "x" * 600 not in response.text


async def test_provider_app_in_use_cannot_be_deleted(
    client: httpx.AsyncClient, google: FakeGoogle
) -> None:
    connection_id = await connect(client)
    apps = await client.get("/internal/provider-apps", headers=internal_headers())
    app_id = apps.json()["provider_apps"][0]["id"]
    path = f"/internal/provider-apps/{app_id}"
    assert (await client.delete(path, headers=internal_headers())).status_code == 409

    await client.delete(
        f"/internal/connections/{connection_id}", headers=internal_headers()
    )
    assert (await client.delete(path, headers=internal_headers())).status_code == 204


# --- start -------------------------------------------------------------------


async def test_start_builds_pkce_authorization_url(
    client: httpx.AsyncClient, engine: AsyncEngine, app: FastAPI
) -> None:
    app_id = await provider_app(client)
    response = await start(client, app_id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["redirect_uri"] == REDIRECT_URI

    url = urlsplit(body["authorization_url"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == GOOGLE_AUTHORIZE_URL
    params = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert params["client_id"] == CLIENT_ID
    assert params["redirect_uri"] == REDIRECT_URI
    assert params["response_type"] == "code"
    assert params["access_type"] == "offline"
    assert params["prompt"] == "consent"
    assert params["include_granted_scopes"] == "true"
    assert params["code_challenge_method"] == "S256"
    assert params["scope"].split() == [
        "openid",
        "email",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.readonly",
    ]
    assert CLIENT_SECRET not in response.text
    state = params["state"]
    assert len(state) >= 43

    async with engine.connect() as conn:
        stored = (
            (await conn.execute(text("SELECT * FROM fallcha_tools.oauth_states")))
            .mappings()
            .one()
        )
    # Stored hashed, bound to org/user/provider/client, verifier encrypted.
    assert stored["state"] == hash_oauth_state(state) != state
    assert (stored["org_id"], stored["user_id"]) == (1, 42)
    assert stored["provider"] == PROVIDER
    assert str(stored["provider_app_id"]) == app_id
    verifier = box(app).decrypt(stored["code_verifier_enc"])
    assert verifier not in stored["code_verifier_enc"]
    assert 43 <= len(verifier) <= 128
    assert params["code_challenge"] == code_challenge(verifier)
    lifetime = stored["expires_at"] - stored["created_at"]
    assert timedelta(minutes=9) < lifetime <= timedelta(minutes=10, seconds=5)


async def test_start_optional_scopes(client: httpx.AsyncClient) -> None:
    params = await started_params(client, optional_scopes=[SHEETS_READONLY_SCOPE])
    assert SHEETS_READONLY_SCOPE in params["scope"].split()

    app_id = await provider_app(client)
    response = await start(
        client,
        app_id,
        optional_scopes=["https://www.googleapis.com/auth/gmail.send"],
    )
    assert response.status_code == 422


async def test_start_rejects_bad_provider_or_app(client: httpx.AsyncClient) -> None:
    app_id = await provider_app(client)
    assert (await start(client, str(uuid.uuid4()))).status_code == 404
    response = await client.post(
        "/internal/oauth/start",
        headers=internal_headers(),
        json={"provider": "echo", "provider_app_id": app_id},
    )
    assert response.status_code == 422
    # Internal routes need the internal secret.
    response = await client.post(
        "/internal/oauth/start",
        json={"provider": PROVIDER, "provider_app_id": app_id},
    )
    assert response.status_code == 401


@pytest.mark.parametrize("missing", ["public_base_url", "ui_return_url"])
async def test_start_is_503_until_configured(
    settings: Settings,
    registry: ProviderRegistry,
    missing: str,
) -> None:
    from fallcha_tools.app import create_app

    application = create_app(settings.model_copy(update={missing: ""}), registry)
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://tools") as c:
        app_id = await provider_app(c)
        response = await start(c, app_id)
    assert response.status_code == 503
    assert "TOOLS_UI_RETURN_URL" in response.json()["detail"]


# --- callback ----------------------------------------------------------------


async def test_callback_creates_encrypted_oauth_connection(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    app: FastAPI,
    google: FakeGoogle,
) -> None:
    params = await started_params(client)
    result = await callback(client, state=params["state"], code="auth-code-1")
    assert result["integration_result"] == "success"
    assert result["provider"] == PROVIDER
    connection_id = result["connection_id"]

    # The code was exchanged with PKCE and the org's client secret.
    sent = form_body(google.token.calls.last.request)
    async with engine.connect() as conn:
        states = (
            await conn.execute(text("SELECT count(*) FROM fallcha_tools.oauth_states"))
        ).scalar_one()
    assert states == 0  # consumed
    assert sent["grant_type"] == "authorization_code"
    assert sent["code"] == "auth-code-1"
    assert sent["redirect_uri"] == REDIRECT_URI
    assert sent["client_id"] == CLIENT_ID
    assert sent["client_secret"] == CLIENT_SECRET
    assert code_challenge(sent["code_verifier"]) == params["code_challenge"]

    stored = await row(engine, connection_id)
    assert stored["auth_mode"] == "oauth2"
    assert stored["org_id"] == 1 and stored["created_by"] == 42
    assert stored["account_label"] == EMAIL
    assert stored["provider_app_id"] is not None
    assert set(GOOGLE_OAUTH.scopes) <= set(stored["scopes_granted"])
    assert stored["config"]["calendar_id"] == "primary"
    for column, plaintext in (
        ("secret_enc", REFRESH_TOKEN),
        ("access_token_enc", ACCESS_TOKEN),
    ):
        assert plaintext not in stored[column]
    assert box(app).decrypt_json(stored["secret_enc"]) == {
        "refresh_token": REFRESH_TOKEN
    }
    assert box(app).decrypt(stored["access_token_enc"]) == ACCESS_TOKEN
    assert stored["expires_at"] > datetime.now(UTC) + timedelta(minutes=50)

    # PENDING until the starting user confirms it from their browser.
    assert stored["status"] == "pending"
    assert stored["pending_user_id"] == 42
    assert stored["pending_nonce_hash"] == hash_browser_nonce(params["browser_nonce"])
    listed = await client.get("/internal/connections", headers=internal_headers())
    assert listed.json()["connections"] == []

    confirmed = await confirm(client, connection_id, params["browser_nonce"])
    assert confirmed.status_code == 200, confirmed.text
    listed = await client.get("/internal/connections", headers=internal_headers())
    assert REFRESH_TOKEN not in listed.text and ACCESS_TOKEN not in listed.text
    [connection] = listed.json()["connections"]
    assert connection["auth_mode"] == "oauth2"
    assert connection["status"] == "active"
    assert connection["account_label"] == EMAIL
    stored = await row(engine, connection_id)
    assert stored["pending_nonce_hash"] is None


async def test_callback_rejects_unknown_tampered_and_replayed_state(
    client: httpx.AsyncClient, google: FakeGoogle
) -> None:
    params = await started_params(client)
    state = params["state"]

    for bad in ("", "x" * 300, state[:-1] + ("A" if state[-1] != "A" else "B")):
        result = await callback(client, state=bad, code="auth-code-xyz")
        assert result == {"integration_result": "error", "reason": "invalid_state"}
    assert not google.token.called

    ok = await callback(client, state=state, code="auth-code-xyz")
    assert ok["integration_result"] == "success"
    replay = await callback(client, state=state, code="auth-code-xyz")
    assert replay == {"integration_result": "error", "reason": "invalid_state"}
    assert google.token.call_count == 1


async def test_concurrent_callbacks_consume_a_state_once(
    client: httpx.AsyncClient, google: FakeGoogle
) -> None:
    params = await started_params(client)
    results = await asyncio.gather(
        *(
            callback(client, state=params["state"], code="auth-code-xyz")
            for _ in range(5)
        )
    )
    outcomes = sorted(r["integration_result"] for r in results)
    assert outcomes == ["error"] * 4 + ["success"]
    assert google.token.call_count == 1


async def test_callback_rejects_expired_state_and_wrong_provider(
    client: httpx.AsyncClient, engine: AsyncEngine, google: FakeGoogle
) -> None:
    params = await started_params(client)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE fallcha_tools.oauth_states"
                " SET expires_at = now() - interval '1 second'"
            )
        )
    result = await callback(client, state=params["state"], code="auth-code-xyz")
    assert result == {"integration_result": "error", "reason": "expired_state"}

    params = await started_params(client)
    response = await client.get(
        "/oauth/echo/callback",
        params={"state": params["state"], "code": "auth-code-xyz"},
    )
    location = response.headers["location"]
    assert parse_qs(urlsplit(location).query)["reason"] == ["invalid_state"]
    assert not google.token.called


async def test_callback_access_denied_consumes_state(
    client: httpx.AsyncClient, google: FakeGoogle
) -> None:
    params = await started_params(client)
    result = await callback(client, state=params["state"], error="access_denied")
    assert result == {"integration_result": "error", "reason": "access_denied"}
    retry = await callback(client, state=params["state"], code="auth-code-xyz")
    assert retry["reason"] == "invalid_state"
    assert not google.token.called


@pytest.mark.parametrize(
    ("token_response", "reason"),
    [
        (httpx.Response(400, json={"error": "invalid_grant"}), "token_exchange_failed"),
        (httpx.Response(503), "token_exchange_failed"),
        (
            httpx.Response(200, json={"access_token": "a", "scope": GRANTED}),
            "no_refresh_token",
        ),
        (
            httpx.Response(
                200,
                json={
                    "access_token": "a",
                    "refresh_token": "r",
                    "scope": "openid https://www.googleapis.com/auth/calendar.events",
                },
            ),
            "scopes_missing",
        ),
    ],
)
async def test_callback_token_failures(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    google: FakeGoogle,
    token_response: httpx.Response,
    reason: str,
) -> None:
    google.token.mock(return_value=token_response)
    params = await started_params(client)
    result = await callback(client, state=params["state"], code="auth-code-xyz")
    assert result == {"integration_result": "error", "reason": reason}
    async with engine.connect() as conn:
        count = (
            await conn.execute(text("SELECT count(*) FROM fallcha_tools.connections"))
        ).scalar_one()
    assert count == 0


async def test_callback_survives_userinfo_failure(
    client: httpx.AsyncClient, engine: AsyncEngine, google: FakeGoogle
) -> None:
    google.router.routes["userinfo"].mock(return_value=httpx.Response(500))
    connection_id = await connect(client)
    assert (await row(engine, connection_id))["account_label"] is None


async def test_oauth_connections_cannot_be_created_directly(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/internal/connections",
        headers=internal_headers(),
        json={
            "provider": PROVIDER,
            "auth_mode": "oauth2",
            "secret": {"refresh_token": "forged"},
        },
    )
    assert response.status_code == 422


# --- refresh -----------------------------------------------------------------


def refreshed(token: str = "ya29.refreshed", **extra: Any) -> httpx.Response:
    return httpx.Response(
        200, json={"access_token": token, "expires_in": 3599, **extra}
    )


async def test_fresh_token_is_used_without_refresh(
    client: httpx.AsyncClient, google: FakeGoogle
) -> None:
    connection_id = await connect(client)
    await client.patch(
        f"/internal/connections/{connection_id}",
        headers=internal_headers(),
        json={"config": calendar_config()},
    )
    exchanges = google.token.call_count
    response = await client.post(
        f"/internal/connections/{connection_id}/test", headers=internal_headers()
    )
    assert response.json()["ok"] is True, response.text
    assert google.token.call_count == exchanges
    sent = google.calendar.calls.last.request.headers["Authorization"]
    assert sent == f"Bearer {ACCESS_TOKEN}"


async def test_expiring_token_is_refreshed_and_stored(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    app: FastAPI,
    google: FakeGoogle,
) -> None:
    connection_id = await connect(client)
    await client.patch(
        f"/internal/connections/{connection_id}",
        headers=internal_headers(),
        json={"config": calendar_config()},
    )
    await expire_access_token(engine, connection_id)
    google.token.mock(return_value=refreshed())

    response = await client.post(
        f"/internal/connections/{connection_id}/test", headers=internal_headers()
    )
    assert response.json()["ok"] is True, response.text
    sent = form_body(google.token.calls.last.request)
    assert sent == {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    auth = google.calendar.calls.last.request.headers["Authorization"]
    assert auth == "Bearer ya29.refreshed"

    stored = await row(engine, connection_id)
    assert box(app).decrypt(stored["access_token_enc"]) == "ya29.refreshed"
    assert stored["expires_at"] > datetime.now(UTC) + timedelta(minutes=50)
    # Google did not rotate it: the refresh token is unchanged.
    assert box(app).decrypt_json(stored["secret_enc"]) == {
        "refresh_token": REFRESH_TOKEN
    }


async def test_concurrent_refreshes_across_processes_hit_google_once(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    app: FastAPI,
    google: FakeGoogle,
) -> None:
    connection_id = await connect(client)
    await expire_access_token(engine, connection_id)

    async def slow_refresh(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.2)
        return refreshed()

    google.token.mock(side_effect=slow_refresh)
    exchanges = google.token.call_count
    svc = services(app)
    # Separate managers with their own engines stand in for separate replicas:
    # only the Postgres locks can serialize them.
    databases = [Database(TEST_DATABASE_URL) for _ in range(4)]
    try:
        managers = [
            OAuthTokenManager(db=db, box=svc.box, http=svc.http) for db in databases
        ]
        tokens = await asyncio.gather(
            *(
                m.access_token(1, uuid.UUID(connection_id), GOOGLE_OAUTH)
                for m in managers
                for _ in range(3)
            )
        )
    finally:
        for db in databases:
            await db.dispose()
    assert {t.token for t in tokens} == {"ya29.refreshed"}
    assert google.token.call_count == exchanges + 1


async def test_in_process_callers_share_one_refresh(
    app: FastAPI,
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    google: FakeGoogle,
) -> None:
    connection_id = await connect(client)
    await client.patch(
        f"/internal/connections/{connection_id}",
        headers=internal_headers(),
        json={"config": calendar_config()},
    )
    await expire_access_token(engine, connection_id)

    async def slow_refresh(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.1)
        return refreshed()

    google.token.mock(side_effect=slow_refresh)
    exchanges = google.token.call_count
    key = await issue_key(client, connection_id)
    async with mcp_client(app, f"http://tools/mcp/{PROVIDER}", key) as mcp:
        results = await asyncio.gather(
            *(mcp.call_tool("check_appointment_availability", {}) for _ in range(4))
        )
    assert all(not r.is_error for r in results)
    assert google.token.call_count == exchanges + 1


async def test_rotated_refresh_token_is_stored(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    app: FastAPI,
    google: FakeGoogle,
) -> None:
    connection_id = await connect(client)
    await expire_access_token(engine, connection_id)
    google.token.mock(return_value=refreshed(refresh_token="1//rotated"))
    svc = services(app)
    manager = OAuthTokenManager(db=svc.db, box=svc.box, http=svc.http)
    await manager.access_token(1, uuid.UUID(connection_id), GOOGLE_OAUTH)

    stored = await row(engine, connection_id)
    assert box(app).decrypt_json(stored["secret_enc"]) == {
        "refresh_token": "1//rotated"
    }
    await expire_access_token(engine, connection_id)
    await manager.access_token(1, uuid.UUID(connection_id), GOOGLE_OAUTH)
    assert form_body(google.token.calls.last.request)["refresh_token"] == "1//rotated"


async def test_rejected_token_forces_one_refresh(
    client: httpx.AsyncClient, google: FakeGoogle
) -> None:
    """Google 401s a token that has not expired (revoked early): refresh once
    and retry with the new token."""
    connection_id = await connect(client)
    await client.patch(
        f"/internal/connections/{connection_id}",
        headers=internal_headers(),
        json={"config": calendar_config()},
    )
    google.token.mock(return_value=refreshed())
    google.calendar.mock(
        side_effect=lambda request: (
            httpx.Response(200, json={"summary": "Bookings"})
            if request.headers["Authorization"] == "Bearer ya29.refreshed"
            else httpx.Response(401, json={"error": {"code": 401}})
        )
    )
    response = await client.post(
        f"/internal/connections/{connection_id}/test", headers=internal_headers()
    )
    assert response.json()["ok"] is True, response.text
    assert google.calendar.call_count == 2


async def test_invalid_grant_marks_connection_and_fails_fast(
    app: FastAPI,
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    google: FakeGoogle,
) -> None:
    connection_id = await connect(client)
    await client.patch(
        f"/internal/connections/{connection_id}",
        headers=internal_headers(),
        json={"config": calendar_config()},
    )
    await expire_access_token(engine, connection_id)
    google.token.mock(
        return_value=httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "revoked"}
        )
    )
    exchanges = google.token.call_count
    key = await issue_key(client, connection_id)
    async with mcp_client(app, f"http://tools/mcp/{PROVIDER}", key) as mcp:
        with pytest.raises(ToolError, match="Google access was revoked or expired"):
            await mcp.call_tool("check_appointment_availability", {})
        # The dead tokens were dropped: no second request to Google.
        with pytest.raises(ToolError, match="reconnect"):
            await mcp.call_tool("check_appointment_availability", {})
    assert google.token.call_count == exchanges + 1
    assert not google.free_busy.called

    stored = await row(engine, connection_id)
    assert stored["status"] == "error"
    assert stored["last_error"] == "Google access was revoked or expired; reconnect"
    assert stored["secret_enc"] is None and stored["access_token_enc"] is None

    svc = services(app)
    manager = OAuthTokenManager(db=svc.db, box=svc.box, http=svc.http)
    with pytest.raises(OAuthReconnectRequired):
        await manager.access_token(1, uuid.UUID(connection_id), GOOGLE_OAUTH)


async def test_missing_sheets_scope_is_reported(
    app: FastAPI, client: httpx.AsyncClient, google: FakeGoogle
) -> None:
    connection_id = await connect(client)
    await client.patch(
        f"/internal/connections/{connection_id}",
        headers=internal_headers(),
        json={"config": calendar_config(orders_sheet_id="sheet-123")},
    )
    key = await issue_key(client, connection_id)
    async with mcp_client(app, f"http://tools/mcp/{PROVIDER}", key) as mcp:
        with pytest.raises(ToolError, match="Google Sheets"):
            await mcp.call_tool(
                "look_up_order",
                {"caller_name": "Ann", "address_or_eircode": "D02 X285"},
            )
    assert not google.sheet.called


async def test_refresh_failure_is_transient(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    google: FakeGoogle,
) -> None:
    connection_id = await connect(client)
    await client.patch(
        f"/internal/connections/{connection_id}",
        headers=internal_headers(),
        json={"config": calendar_config()},
    )
    await expire_access_token(engine, connection_id)
    google.token.mock(side_effect=httpx.ConnectError("down"))
    response = await client.post(
        f"/internal/connections/{connection_id}/test", headers=internal_headers()
    )
    assert response.json()["ok"] is False
    assert "could not reach Google" in response.json()["message"]
    stored = await row(engine, connection_id)
    # Tokens are kept: the next call simply retries.
    assert stored["secret_enc"] is not None


# --- keys --------------------------------------------------------------------


async def test_exclusive_key_issue_and_single_key_revoke(
    client: httpx.AsyncClient, google: FakeGoogle
) -> None:
    connection_id = await connect(client)
    path = f"/internal/connections/{connection_id}/keys"
    first = await client.post(
        path, headers=internal_headers(), json={"exclusive": True}
    )
    assert first.status_code == 201
    again = await client.post(
        path, headers=internal_headers(), json={"exclusive": True}
    )
    assert again.status_code == 409

    key_id = first.json()["id"]
    other_org = await client.delete(f"{path}/{key_id}", headers=internal_headers(2))
    assert other_org.status_code == 404
    revoked = await client.delete(f"{path}/{key_id}", headers=internal_headers())
    assert revoked.status_code == 204
    assert (
        await client.delete(f"{path}/{key_id}", headers=internal_headers())
    ).status_code == 204
    again = await client.post(
        path, headers=internal_headers(), json={"exclusive": True}
    )
    assert again.status_code == 201


async def test_rejected_client_marks_error_but_keeps_tokens(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    app: FastAPI,
    google: FakeGoogle,
) -> None:
    connection_id = await connect(client)
    await expire_access_token(engine, connection_id)
    google.token.mock(
        return_value=httpx.Response(401, json={"error": "invalid_client"})
    )
    svc = services(app)
    manager = OAuthTokenManager(db=svc.db, box=svc.box, http=svc.http)
    with pytest.raises(OAuthReconnectRequired, match="rejected the OAuth client"):
        await manager.access_token(1, uuid.UUID(connection_id), GOOGLE_OAUTH)
    stored = await row(engine, connection_id)
    assert stored["status"] == "error"
    assert CLIENT_SECRET not in (stored["last_error"] or "")
    # The refresh token may still be good once the client is fixed.
    assert stored["secret_enc"] is not None


# --- review follow-ups: browser-bound confirmation -----------------------------


async def test_pending_connection_is_unusable_until_confirmed(
    client: httpx.AsyncClient, google: FakeGoogle
) -> None:
    connection_id, nonce = await connect_pending(client)
    headers = internal_headers(1, user_id=42)
    issued = await client.post(
        f"/internal/connections/{connection_id}/keys", headers=headers, json={}
    )
    assert issued.status_code == 409
    tested = await client.post(
        f"/internal/connections/{connection_id}/test", headers=headers
    )
    assert tested.status_code == 409

    # Another org, another user, or another browser cannot confirm it.
    assert (await confirm(client, connection_id, nonce, org_id=2)).status_code == 404
    assert (await confirm(client, connection_id, nonce, user_id=43)).status_code == 409
    wrong = await confirm(client, connection_id, nonce[:-2] + "xx")
    assert wrong.status_code == 409
    assert "same browser" in wrong.json()["detail"]

    assert (await confirm(client, connection_id, nonce)).status_code == 200
    # Confirming again is a no-op; the key can now be issued.
    assert (await confirm(client, connection_id, "anything")).status_code == 200
    issued = await client.post(
        f"/internal/connections/{connection_id}/keys", headers=headers, json={}
    )
    assert issued.status_code == 201


async def test_unconfirmed_connections_are_swept(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    google: FakeGoogle,
) -> None:
    connection_id, nonce = await connect_pending(client)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE fallcha_tools.connections"
                " SET created_at = now() - interval '11 minutes' WHERE id = :id"
            ),
            {"id": connection_id},
        )
    # Starting another flow sweeps it.
    await started_params(client)
    stored = await row(engine, connection_id)
    assert stored["status"] == "revoked"
    assert stored["secret_enc"] is None and stored["access_token_enc"] is None
    assert (await confirm(client, connection_id, nonce)).status_code == 409


async def test_revoke_all_keys(client: httpx.AsyncClient, google: FakeGoogle) -> None:
    connection_id = await connect(client)
    path = f"/internal/connections/{connection_id}/keys"
    for _ in range(2):
        assert (await client.post(path, headers=internal_headers())).status_code == 201
    other = await client.delete(path, headers=internal_headers(2))
    assert other.status_code == 404
    assert (await client.delete(path, headers=internal_headers())).status_code == 204
    exclusive = await client.post(
        path, headers=internal_headers(), json={"exclusive": True}
    )
    assert exclusive.status_code == 201


# --- review follow-ups: error codes and recovery -------------------------------


async def test_successful_refresh_clears_a_previous_error(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    app: FastAPI,
    google: FakeGoogle,
) -> None:
    connection_id = await connect(client)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE fallcha_tools.connections SET status = 'error',"
                " last_error = 'calendar not shared',"
                " expires_at = now() + interval '1 minute' WHERE id = :id"
            ),
            {"id": connection_id},
        )
    google.token.mock(return_value=refreshed())
    svc = services(app)
    manager = OAuthTokenManager(db=svc.db, box=svc.box, http=svc.http)
    await manager.access_token(1, uuid.UUID(connection_id), GOOGLE_OAUTH)
    stored = await row(engine, connection_id)
    assert (stored["status"], stored["last_error"], stored["error_code"]) == (
        "active",
        None,
        None,
    )


async def test_rejected_client_fails_fast_afterwards(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    app: FastAPI,
    google: FakeGoogle,
) -> None:
    connection_id = await connect(client)
    await expire_access_token(engine, connection_id)
    google.token.mock(
        return_value=httpx.Response(401, json={"error": "invalid_client"})
    )
    exchanges = google.token.call_count
    svc = services(app)
    manager = OAuthTokenManager(db=svc.db, box=svc.box, http=svc.http)
    for _ in range(3):
        with pytest.raises(OAuthReconnectRequired, match="rejected the OAuth client"):
            await manager.access_token(1, uuid.UUID(connection_id), GOOGLE_OAUTH)
    assert google.token.call_count == exchanges + 1
    assert (await row(engine, connection_id))["error_code"] == "client_rejected"
    listed = await client.get("/internal/connections", headers=internal_headers())
    assert listed.json()["connections"][0]["error_code"] == "client_rejected"


# --- review follow-ups: cancellation, budget, shared rejection -----------------


async def test_cancelled_caller_does_not_abort_the_refresh(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    app: FastAPI,
    google: FakeGoogle,
) -> None:
    connection_id = await connect(client)
    await expire_access_token(engine, connection_id)

    async def slow_refresh(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.2)
        return refreshed(refresh_token="1//rotated-late")

    google.token.mock(side_effect=slow_refresh)
    svc = services(app)
    manager = OAuthTokenManager(db=svc.db, box=svc.box, http=svc.http)
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await manager.access_token(1, uuid.UUID(connection_id), GOOGLE_OAUTH)
    await asyncio.sleep(0.4)
    stored = await row(engine, connection_id)
    assert box(app).decrypt(stored["access_token_enc"]) == "ya29.refreshed"
    assert box(app).decrypt_json(stored["secret_enc"]) == {
        "refresh_token": "1//rotated-late"
    }


@dataclass
class FakeTokens:
    """OAuthAccess double: hands out "old" until it is rejected."""

    calls: list[str | None]

    async def access_token(self, *, rejected: str | None = None) -> AccessToken:
        self.calls.append(rejected)
        token = "new" if rejected == "old" else "old"
        return AccessToken(token, datetime.now(UTC) + timedelta(hours=1))


async def test_token_rejection_is_shared_across_calls() -> None:
    """Two tool calls hold the same token; Google refuses it for the first.
    The second call (its own credentials object) must not get it back."""
    cache = TokenCache()
    connection_id = uuid.uuid4()
    tokens = FakeTokens(calls=[])
    scopes = ["https://www.googleapis.com/auth/calendar"]
    granted = [
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.readonly",
    ]

    def credentials() -> OAuthCredentials:
        return OAuthCredentials(
            connection_id=connection_id,
            tokens=tokens,
            cache=cache,
            scopes_granted=granted,
        )

    first, second = credentials(), credentials()
    assert await first.access_token(scopes) == "old"
    assert await second.access_token(scopes) == "old"
    first.invalidate(scopes)
    assert await credentials().access_token(scopes) == "new"
    assert tokens.calls == [None, "old"]
    # A late invalidation of the old token keeps the new one cached.
    second.invalidate(scopes)
    assert await credentials().access_token(scopes) == "new"
    assert len(tokens.calls) == 2


async def test_token_fetch_respects_the_budget() -> None:
    class SlowCredentials:
        async def access_token(self, scopes: Sequence[str]) -> str:
            await asyncio.sleep(1)
            return "late"

        def invalidate(self, scopes: Sequence[str]) -> None:
            del scopes

    async with httpx.AsyncClient() as http:
        google = GoogleClient(http=http, credentials=SlowCredentials())
        budget = Budget(
            deadline_at=asyncio.get_running_loop().time() + 0.05, min_seconds=0.01
        )
        started = asyncio.get_running_loop().time()
        with pytest.raises(GoogleApiError, match="took too long"):
            await google.insert_event("cal", {"id": "e"}, budget=budget)
        assert asyncio.get_running_loop().time() - started < 0.5


# --- review follow-ups: logs ---------------------------------------------------


def test_access_log_redacts_callback_query() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        (
            "1.2.3.4:5",
            "GET",
            "/oauth/google-calendar/callback?code=c0de&state=s",
            "1.1",
            302,
        ),
        None,
    )
    assert RedactOAuthQuery().filter(record)
    message = record.getMessage()
    assert "c0de" not in message and "state=s" not in message
    assert "/oauth/google-calendar/callback?<redacted>" in message
    other = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        "%s %s %s",
        ("1.2.3.4:5", "GET", "/health?x=1"),
        None,
    )
    RedactOAuthQuery().filter(other)
    assert "/health?x=1" in other.getMessage()


async def test_callback_never_logs_a_malformed_provider_id(
    client: httpx.AsyncClient,
) -> None:
    lines: list[str] = []
    sink = loguru_logger.add(lines.append, level="DEBUG")
    try:
        response = await client.get(
            "/oauth/EVIL-injected%20line/callback", params={"state": "x" * 50}
        )
    finally:
        loguru_logger.remove(sink)
    assert response.status_code == 302
    logged = "".join(lines)
    assert "EVIL" not in logged and "x" * 50 not in logged
