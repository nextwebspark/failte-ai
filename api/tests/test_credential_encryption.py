"""Encryption at rest of ``external_credentials.credential_data``.

Every database test runs inside the conftest's rolled-back transaction, so the
shared test database never keeps rows encrypted with a throwaway key.
"""

from __future__ import annotations

import importlib.util
import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from api.db.credential_encryption_client import CredentialEncryptionClient
from api.db.models import OrganizationModel, UserModel
from api.services.tool_integrations.resources import (
    DbIntegrationResources,
    is_integration_managed,
)
from api.services.workflow.mcp_tool_session import build_streamable_http_params
from api.utils import credential_crypto
from api.utils.credential_auth import build_auth_header
from api.utils.credential_crypto import (
    CredentialCipher,
    CredentialDecryptionError,
    decrypt_credential_data,
    encrypt_credential_data,
    generate_key,
    is_envelope,
)

SECRET = "s3cr3t-token-must-never-be-stored-in-clear"

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "6b0c8484ba5a_encrypt_external_credentials.py"
)
_spec = importlib.util.spec_from_file_location("encrypt_credentials", _MIGRATION_PATH)
assert _spec and _spec.loader
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


@pytest.fixture
def key() -> str:
    return generate_key()


@pytest.fixture
def encryption_on(monkeypatch, key):
    monkeypatch.setattr(credential_crypto, "_cipher", CredentialCipher([key]))
    return key


@pytest.fixture
def encryption_off(monkeypatch):
    monkeypatch.setattr(credential_crypto, "_cipher", None)


# -- cipher unit tests ---------------------------------------------------------


def test_round_trip_produces_an_opaque_envelope(key):
    cipher = CredentialCipher([key])
    data = {"token": SECRET, "fallcha_integration": {"provider": "x"}}
    envelope = cipher.seal(data)
    assert is_envelope(envelope)
    assert envelope["_enc"] == "v1"
    assert SECRET not in json.dumps(envelope)
    assert cipher.open(envelope) == data


def test_rotation_moves_to_the_primary_key():
    old, new = generate_key(), generate_key()
    envelope = CredentialCipher([old]).seal({"token": SECRET})
    rotated = CredentialCipher([new, old]).rotate(envelope)
    assert rotated["ct"] != envelope["ct"]
    # Only the new key is needed once rotated.
    assert CredentialCipher([new]).open(rotated) == {"token": SECRET}
    with pytest.raises(CredentialDecryptionError):
        CredentialCipher([new]).open(envelope)


def test_unknown_version_and_wrong_key_are_rejected(key):
    envelope = CredentialCipher([key]).seal({"token": SECRET})
    with pytest.raises(CredentialDecryptionError):
        CredentialCipher([generate_key()]).open(envelope)
    with pytest.raises(CredentialDecryptionError, match="version"):
        CredentialCipher([key]).open({**envelope, "_enc": "v9"})


def test_invalid_key_fails_without_echoing_it():
    with pytest.raises(ValueError) as exc_info:
        CredentialCipher(["not-a-fernet-key"])
    assert "not-a-fernet-key" not in str(exc_info.value)
    with pytest.raises(ValueError):
        CredentialCipher([])


def test_legacy_plaintext_is_read_in_both_modes(monkeypatch, key):
    legacy = {"token": SECRET}
    monkeypatch.setattr(credential_crypto, "_cipher", None)
    assert decrypt_credential_data(legacy) == legacy
    monkeypatch.setattr(credential_crypto, "_cipher", CredentialCipher([key]))
    assert decrypt_credential_data(legacy) == legacy


def test_plaintext_mode_stores_as_is_and_cannot_open_envelopes(encryption_off, key):
    assert encrypt_credential_data({"token": SECRET}) == {"token": SECRET}
    envelope = CredentialCipher([key]).seal({"token": SECRET})
    with pytest.raises(CredentialDecryptionError, match="not set"):
        decrypt_credential_data(envelope)


@pytest.mark.parametrize("mode", ["on", "off"])
def test_envelope_shaped_plaintext_is_refused(monkeypatch, key, mode):
    monkeypatch.setattr(
        credential_crypto, "_cipher", CredentialCipher([key]) if mode == "on" else None
    )
    with pytest.raises(ValueError, match="reserved"):
        encrypt_credential_data({"_enc": "v1", "ct": "forged"})
    # Extra keys make it ordinary data.
    assert not is_envelope({"_enc": "v1", "ct": "x", "token": "y"})


# -- database ------------------------------------------------------------------


async def _org_and_user(async_session) -> tuple[OrganizationModel, UserModel]:
    organization = OrganizationModel(provider_id=f"enc-org-{uuid.uuid4().hex}")
    async_session.add(organization)
    await async_session.flush()
    user = UserModel(
        provider_id=f"enc-user-{uuid.uuid4().hex}",
        selected_organization_id=organization.id,
    )
    async_session.add(user)
    await async_session.flush()
    return organization, user


async def _raw_data(async_session, credential_uuid: str) -> object:
    stored = await async_session.scalar(
        text(
            "SELECT credential_data::text FROM external_credentials "
            "WHERE credential_uuid = :uuid"
        ),
        {"uuid": credential_uuid},
    )
    return json.loads(stored)


async def _reload(async_session, db_session, credential_uuid, organization_id):
    # Drop identity-map copies so the value really comes from the database.
    async_session.expunge_all()
    return await db_session.get_credential_by_uuid(credential_uuid, organization_id)


async def test_ciphertext_at_rest_and_transparent_reads(
    db_session, async_session, encryption_on
):
    org, user = await _org_and_user(async_session)
    credential = await db_session.create_credential(
        organization_id=org.id,
        user_id=user.id,
        name="enc",
        credential_type="bearer_token",
        credential_data={"token": SECRET},
    )
    uuid_ = credential.credential_uuid

    raw = await _raw_data(async_session, uuid_)
    assert is_envelope(raw)
    assert SECRET not in json.dumps(raw)

    loaded = await _reload(async_session, db_session, uuid_, org.id)
    assert loaded.credential_data == {"token": SECRET}
    assert build_auth_header(loaded) == {"Authorization": f"Bearer {SECRET}"}
    params = build_streamable_http_params(
        url="https://mcp.example.com/mcp",
        credential=loaded,
        timeout_secs=5,
        sse_read_timeout_secs=5,
    )
    assert params.headers == {"Authorization": f"Bearer {SECRET}"}

    # Updates (a Core UPDATE through the client) are encrypted too.
    await db_session.update_credential(
        credential_uuid=uuid_,
        organization_id=org.id,
        credential_type="basic_auth",
        credential_data={"username": "u", "password": SECRET},
    )
    raw = await _raw_data(async_session, uuid_)
    assert is_envelope(raw) and SECRET not in json.dumps(raw)
    loaded = await _reload(async_session, db_session, uuid_, org.id)
    assert loaded.credential_data == {"username": "u", "password": SECRET}
    assert build_auth_header(loaded)["Authorization"].startswith("Basic ")


async def test_legacy_plaintext_row_is_readable_after_enabling(
    db_session, async_session, monkeypatch, key
):
    org, user = await _org_and_user(async_session)
    monkeypatch.setattr(credential_crypto, "_cipher", None)
    credential = await db_session.create_credential(
        organization_id=org.id,
        user_id=user.id,
        name="legacy",
        credential_type="api_key",
        credential_data={"header_name": "X-Key", "api_key": SECRET},
    )
    assert await _raw_data(async_session, credential.credential_uuid) == {
        "header_name": "X-Key",
        "api_key": SECRET,
    }

    monkeypatch.setattr(credential_crypto, "_cipher", CredentialCipher([key]))
    loaded = await _reload(
        async_session, db_session, credential.credential_uuid, org.id
    )
    assert build_auth_header(loaded) == {"X-Key": SECRET}


async def test_reencrypt_seals_plaintext_and_rotates_envelopes(
    db_session, async_session, db_connection, monkeypatch
):
    old, new = generate_key(), generate_key()
    org, user = await _org_and_user(async_session)

    monkeypatch.setattr(credential_crypto, "_cipher", None)
    plain = await db_session.create_credential(
        organization_id=org.id,
        user_id=user.id,
        name="plain",
        credential_type="bearer_token",
        credential_data={"token": "plain-" + SECRET},
    )
    monkeypatch.setattr(credential_crypto, "_cipher", CredentialCipher([old]))
    sealed = await db_session.create_credential(
        organization_id=org.id,
        user_id=user.id,
        name="sealed",
        credential_type="bearer_token",
        credential_data={"token": "old-" + SECRET},
    )
    # A row sealed under a key the rotation will not know.
    stranger_raw = CredentialCipher([generate_key()]).seal({"token": "x"})
    stranger_uuid = await _insert_raw(async_session, org, user, stranger_raw)
    sealed_raw_before = await _raw_data(async_session, sealed.credential_uuid)
    await async_session.flush()

    rotating = CredentialCipher([new, old])
    client = CredentialEncryptionClient(db_connection)
    dry = await client.reencrypt_all(rotating, batch_size=2, dry_run=True)
    assert await _raw_data(async_session, plain.credential_uuid) == {
        "token": "plain-" + SECRET
    }
    report = await client.reencrypt_all(rotating, batch_size=2)
    assert report.scanned == dry.scanned >= 3
    stranger_id = await async_session.scalar(
        text("SELECT id FROM external_credentials WHERE credential_uuid = :u"),
        {"u": stranger_uuid},
    )
    assert stranger_id in report.failed_ids
    assert await _raw_data(async_session, stranger_uuid) == stranger_raw

    plain_raw = await _raw_data(async_session, plain.credential_uuid)
    sealed_raw = await _raw_data(async_session, sealed.credential_uuid)
    assert is_envelope(plain_raw) and is_envelope(sealed_raw)
    assert sealed_raw != sealed_raw_before
    only_new = CredentialCipher([new])
    assert only_new.open(plain_raw) == {"token": "plain-" + SECRET}
    assert only_new.open(sealed_raw) == {"token": "old-" + SECRET}

    # Idempotent: a second pass only re-rotates; data is unchanged.
    await client.reencrypt_all(rotating, batch_size=50)
    assert only_new.open(await _raw_data(async_session, plain.credential_uuid)) == {
        "token": "plain-" + SECRET
    }


async def test_integration_credentials_and_guard_work_encrypted(
    db_session, async_session, test_client_factory, encryption_on
):
    org, user = await _org_and_user(async_session)
    resources = DbIntegrationResources()
    connection_id = uuid.uuid4()
    credential_uuid = await resources.create_credential(
        organization_id=org.id,
        user_id=user.id,
        name="Google Calendar",
        description="integration",
        provider="google-calendar",
        connection_id=connection_id,
    )
    await resources.store_connection_key(
        organization_id=org.id,
        credential_uuid=credential_uuid,
        provider="google-calendar",
        connection_id=connection_id,
        key=SECRET,
    )
    raw = await _raw_data(async_session, credential_uuid)
    assert is_envelope(raw)
    assert SECRET not in json.dumps(raw)
    assert "fallcha_integration" not in json.dumps(raw)

    async_session.expunge_all()
    linked = await resources.list_linked_credentials(org.id)
    assert [(c.credential_uuid, c.connection_id) for c in linked] == [
        (credential_uuid, connection_id)
    ]
    loaded = await _reload(async_session, db_session, credential_uuid, org.id)
    assert is_integration_managed(loaded.credential_data)
    assert build_auth_header(loaded) == {"Authorization": f"Bearer {SECRET}"}

    async with test_client_factory(user) as client:
        response = await client.put(
            f"/api/v1/credentials/{credential_uuid}",
            json={"credential_data": {"token": "x"}},
        )
        assert response.status_code == 409
        response = await client.get(f"/api/v1/credentials/{credential_uuid}")
        assert response.status_code == 200
        assert "credential_data" not in response.json()
        assert SECRET not in response.text

    await resources.delete_credential(
        organization_id=org.id, credential_uuid=credential_uuid
    )
    assert await resources.list_linked_credentials(org.id) == []
    deleted = await resources.list_linked_credentials(org.id, include_deleted=True)
    assert [c.credential_uuid for c in deleted] == [credential_uuid]


# -- migration -----------------------------------------------------------------


async def _insert_raw(async_session, org, user, data: dict) -> str:
    credential_uuid = str(uuid.uuid4())
    await async_session.execute(
        text(
            "INSERT INTO external_credentials (credential_uuid, organization_id, "
            "name, credential_type, credential_data, created_by, is_active) "
            "VALUES (:uuid, :org, :name, 'bearer_token', CAST(:data AS json), "
            ":user, true)"
        ),
        {
            "uuid": credential_uuid,
            "org": org.id,
            "name": f"m-{credential_uuid}",
            "data": json.dumps(data),
            "user": user.id,
        },
    )
    return credential_uuid


async def _run_migration(db_connection, monkeypatch, step: str) -> None:
    def _run(sync_connection):
        monkeypatch.setattr(
            migration, "op", SimpleNamespace(get_bind=lambda: sync_connection)
        )
        getattr(migration, step)()

    await db_connection.run_sync(_run)


async def test_migration_upgrade_and_downgrade(
    async_session, db_connection, monkeypatch, key
):
    org, user = await _org_and_user(async_session)
    plain_uuid = await _insert_raw(async_session, org, user, {"token": SECRET})
    await async_session.flush()

    # Keep any ambient keys so rows other tests committed under them still
    # decrypt on downgrade (the migration covers the whole table).
    ambient = os.environ.get("CREDENTIALS_ENCRYPTION_KEYS", "")

    # Without keys: no-op.
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEYS", raising=False)
    await _run_migration(db_connection, monkeypatch, "upgrade")
    assert await _raw_data(async_session, plain_uuid) == {"token": SECRET}

    monkeypatch.setenv(
        "CREDENTIALS_ENCRYPTION_KEYS", ",".join(filter(None, [key, ambient]))
    )
    monkeypatch.setattr(migration, "BATCH_SIZE", 1)
    await _run_migration(db_connection, monkeypatch, "upgrade")
    sealed = await _raw_data(async_session, plain_uuid)
    assert is_envelope(sealed)
    assert CredentialCipher([key]).open(sealed) == {"token": SECRET}

    # Idempotent: envelopes are left alone.
    await _run_migration(db_connection, monkeypatch, "upgrade")
    assert await _raw_data(async_session, plain_uuid) == sealed

    await _run_migration(db_connection, monkeypatch, "downgrade")
    assert await _raw_data(async_session, plain_uuid) == {"token": SECRET}


async def test_migration_downgrade_refuses_without_keys(
    async_session, db_connection, monkeypatch, key
):
    org, user = await _org_and_user(async_session)
    envelope = CredentialCipher([key]).seal({"token": SECRET})
    sealed_uuid = await _insert_raw(async_session, org, user, envelope)
    await async_session.flush()

    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEYS", raising=False)
    with pytest.raises(RuntimeError, match="cannot be decrypted"):
        await _run_migration(db_connection, monkeypatch, "downgrade")
    assert await _raw_data(async_session, sealed_uuid) == envelope


def test_migration_envelope_matches_the_application_format(key, monkeypatch):
    """The migration's frozen envelope must stay readable by the app."""
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEYS", key)
    fernet = migration._fernet()
    token = fernet.encrypt(json.dumps({"token": SECRET}).encode()).decode()
    envelope = {migration.ENVELOPE_MARKER: migration.ENVELOPE_VERSION, "ct": token}
    assert migration._is_envelope(envelope) and is_envelope(envelope)
    assert CredentialCipher([key]).open(envelope) == {"token": SECRET}
