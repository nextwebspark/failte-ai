from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from fallcha_tools.app import create_app
from fallcha_tools.config import Settings
from fallcha_tools.core.crypto import SecretBox
from fallcha_tools.core.db import Database
from fallcha_tools.core.keys import hash_connection_key
from fallcha_tools.core.repositories import (
    ConnectionNotFoundError,
    ConnectionRepository,
    KeyRepository,
)
from tests.conftest import (
    INTERNAL_SECRET,
    create_echo_connection,
    internal_headers,
    issue_key,
)


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.json() == {"status": "ok"}


async def test_missing_or_wrong_internal_secret_rejected(
    client: httpx.AsyncClient,
) -> None:
    no_secret = await client.get(
        "/internal/catalog", headers={"X-Org-Id": "1", "X-User-Id": "1"}
    )
    assert no_secret.status_code == 401
    wrong = await client.get(
        "/internal/catalog",
        headers={**internal_headers(), "X-Internal-Secret": INTERNAL_SECRET + "x"},
    )
    assert wrong.status_code == 401


async def test_missing_org_or_user_header_rejected(client: httpx.AsyncClient) -> None:
    headers = internal_headers()
    del headers["X-Org-Id"]
    response = await client.get("/internal/connections", headers=headers)
    assert response.status_code == 400

    headers = internal_headers()
    del headers["X-User-Id"]
    response = await client.get("/internal/connections", headers=headers)
    assert response.status_code == 400

    for bad_org in ("abc", "0", "-3"):
        bad = await client.get(
            "/internal/connections",
            headers={**internal_headers(), "X-Org-Id": bad_org},
        )
        assert bad.status_code == 400

    wrong_secret_bad_org = await client.get(
        "/internal/connections",
        headers={"X-Internal-Secret": "nope", "X-Org-Id": "abc"},
    )
    assert wrong_secret_bad_org.status_code == 401


async def test_catalog_lists_registered_providers(client: httpx.AsyncClient) -> None:
    response = await client.get("/internal/catalog", headers=internal_headers())
    assert response.status_code == 200
    providers = {p["id"]: p for p in response.json()["providers"]}
    assert set(providers) == {"echo", "echo-b"}
    echo = providers["echo"]
    assert echo["title"] == "Echo"
    assert echo["auth_modes"] == ["api_key"]
    assert {t["name"] for t in echo["tools"]} == {"echo", "whoami"}


async def test_create_connection_stores_ciphertext_only(
    client: httpx.AsyncClient, engine: AsyncEngine, settings: Settings
) -> None:
    connection_id = await create_echo_connection(client, api_key="plain-api-key")
    async with engine.connect() as conn:
        secret_enc = (
            await conn.execute(
                text("SELECT secret_enc FROM fallcha_tools.connections WHERE id = :id"),
                {"id": connection_id},
            )
        ).scalar_one()
    assert "plain-api-key" not in secret_enc
    box = SecretBox(settings.encryption_keys)
    assert box.decrypt_json(secret_enc) == {"api_key": "plain-api-key"}

    listed = await client.get("/internal/connections", headers=internal_headers())
    body = listed.json()["connections"]
    assert [c["id"] for c in body] == [connection_id]
    assert "secret" not in str(body).lower().replace("secret_", "")
    assert body[0]["status"] == "active"


async def test_create_connection_validates_provider_and_auth_mode(
    client: httpx.AsyncClient,
) -> None:
    async def post(payload: dict[str, object]) -> httpx.Response:
        return await client.post(
            "/internal/connections", headers=internal_headers(), json=payload
        )

    unknown = await post(
        {"provider": "nope", "auth_mode": "api_key", "secret": {"k": "v"}}
    )
    assert unknown.status_code == 404
    unsupported = await post(
        {"provider": "echo", "auth_mode": "service_account", "secret": {"k": "v"}}
    )
    assert unsupported.status_code == 422
    oauth = await post(
        {"provider": "echo", "auth_mode": "oauth2", "secret": {"k": "v"}}
    )
    assert oauth.status_code == 422
    empty = await post({"provider": "echo", "auth_mode": "api_key", "secret": {}})
    assert empty.status_code == 422


async def test_issue_lookup_and_revoke_key(
    client: httpx.AsyncClient, engine: AsyncEngine, settings: Settings
) -> None:
    connection_id = await create_echo_connection(client)
    key = await issue_key(client, connection_id)
    assert key.startswith("ftk_")

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT key_hash, fallcha_credential_uuid"
                    " FROM fallcha_tools.connection_keys"
                )
            )
        ).one()
    assert row.key_hash == hash_connection_key(key)
    assert row.fallcha_credential_uuid == "cred-123"

    db = Database(settings.database_url)
    try:
        async with db.session() as session:
            principal = await KeyRepository(session).lookup_key(key)
            assert principal is not None
            assert principal.org_id == 1
            assert str(principal.connection_id) == connection_id
            assert principal.provider == "echo"
            assert await KeyRepository(session).lookup_key("ftk_" + "x" * 40) is None
            assert await KeyRepository(session).lookup_key("garbage") is None

        revoked = await client.delete(
            f"/internal/connections/{connection_id}", headers=internal_headers()
        )
        assert revoked.status_code == 204

        async with db.session() as session:
            assert await KeyRepository(session).lookup_key(key) is None
    finally:
        await db.dispose()

    listed = await client.get("/internal/connections", headers=internal_headers())
    assert listed.json()["connections"] == []
    with_revoked = await client.get(
        "/internal/connections?include_revoked=true", headers=internal_headers()
    )
    [revoked_row] = with_revoked.json()["connections"]
    assert revoked_row["status"] == "revoked"

    async with engine.connect() as conn:
        secret_enc = (
            await conn.execute(text("SELECT secret_enc FROM fallcha_tools.connections"))
        ).scalar_one()
    assert secret_enc is None

    again = await client.post(
        f"/internal/connections/{connection_id}/keys", headers=internal_headers()
    )
    assert again.status_code == 409


async def test_other_org_cannot_touch_connection(client: httpx.AsyncClient) -> None:
    connection_id = await create_echo_connection(client, org_id=1)
    other = internal_headers(org_id=2)

    get = await client.get(f"/internal/connections/{connection_id}", headers=other)
    assert get.status_code == 404
    key = await client.post(
        f"/internal/connections/{connection_id}/keys", headers=other
    )
    assert key.status_code == 404
    delete = await client.delete(
        f"/internal/connections/{connection_id}", headers=other
    )
    assert delete.status_code == 404
    listed = await client.get("/internal/connections", headers=other)
    assert listed.json()["connections"] == []

    own = await client.get(
        f"/internal/connections/{connection_id}", headers=internal_headers(org_id=1)
    )
    assert own.status_code == 200
    assert own.json()["status"] == "active"


async def test_unknown_connection_is_404(client: httpx.AsyncClient) -> None:
    response = await client.get(
        f"/internal/connections/{uuid.uuid4()}", headers=internal_headers()
    )
    assert response.status_code == 404


async def test_connection_test_updates_status(client: httpx.AsyncClient) -> None:
    good = await create_echo_connection(client, api_key="good")
    bad = await create_echo_connection(client, api_key="bad")

    ok = await client.post(
        f"/internal/connections/{good}/test", headers=internal_headers()
    )
    assert ok.json()["ok"] is True
    assert ok.json()["connection"]["account_label"] == "echo-account"

    failed = await client.post(
        f"/internal/connections/{bad}/test", headers=internal_headers()
    )
    assert failed.json()["ok"] is False
    assert failed.json()["connection"]["status"] == "error"
    assert failed.json()["connection"]["last_error"] == "bad api key"


def test_rejects_bad_settings(settings: Settings) -> None:

    invalid: dict[str, Any] = {
        "DATABASE_URL": settings.database_url,
        "TOOLS_ENCRYPTION_KEYS": " , ",
        "TOOLS_INTERNAL_SECRET": INTERNAL_SECRET,
    }
    with pytest.raises(ValidationError):
        Settings(**invalid)
    with pytest.raises(ValidationError):
        Settings(
            **{
                **invalid,
                "TOOLS_ENCRYPTION_KEYS": "k",
                "TOOLS_INTERNAL_SECRET": "short",
            }
        )
    with pytest.raises(ValueError):
        create_app(
            settings.model_copy(update={"encryption_keys_raw": SecretStr("bad")})
        )


async def test_keys_and_secrets_are_org_bound(
    client: httpx.AsyncClient, engine: AsyncEngine, settings: Settings
) -> None:
    connection_id = await create_echo_connection(client, org_id=1)
    key = await issue_key(client, connection_id, org_id=1)

    db = Database(settings.database_url)
    try:
        async with db.session() as session:
            repo = ConnectionRepository(session, SecretBox(settings.encryption_keys))
            with pytest.raises(ConnectionNotFoundError):
                await repo.load_secrets(2, uuid.UUID(connection_id))
            loaded = await repo.load_secrets(1, uuid.UUID(connection_id))
            assert loaded.secret == {"api_key": "good"}

        # A key row whose org disagrees with its connection's org is inert.
        async with engine.begin() as conn:
            await conn.execute(
                text("UPDATE fallcha_tools.connection_keys SET org_id = 2")
            )
        async with db.session() as session:
            assert await KeyRepository(session).lookup_key(key) is None
    finally:
        await db.dispose()
