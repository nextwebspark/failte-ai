"""Encryption at rest of telephony credentials, integration connection
details and organization configuration values (GDPR Art. 32).

Same envelope and keys as ``external_credentials.credential_data`` (see
test_credential_encryption.py). Every database test runs inside the conftest's
rolled-back transaction.
"""

from __future__ import annotations

import importlib.util
import json
import os
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from api.db.credential_encryption_client import (
    ENCRYPTED_COLUMNS,
    CredentialEncryptionClient,
)
from api.db.encrypted_json import EncryptedJSON
from api.db.models import Base, OrganizationModel, UserModel
from api.enums import OrganizationConfigurationKey
from api.utils import credential_crypto
from api.utils.cors import CorsConfigurationError, resolve_cors_settings
from api.utils.credential_crypto import CredentialCipher, generate_key, is_envelope

SECRET = "s3cr3t-must-never-be-stored-in-clear"

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "00cb7a7a62b1_encrypt_telephony_integration_org_config.py"
)
_spec = importlib.util.spec_from_file_location(
    "encrypt_secret_columns", _MIGRATION_PATH
)
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


async def _org_and_user(async_session) -> tuple[OrganizationModel, UserModel]:
    organization = OrganizationModel(provider_id=f"sec-org-{uuid.uuid4().hex}")
    async_session.add(organization)
    await async_session.flush()
    user = UserModel(
        provider_id=f"sec-user-{uuid.uuid4().hex}",
        selected_organization_id=organization.id,
    )
    async_session.add(user)
    await async_session.flush()
    return organization, user


async def _raw(async_session, table: str, column: str, row_id: int) -> object:
    stored = await async_session.scalar(
        text(f"SELECT {column}::text FROM {table} WHERE id = :id"), {"id": row_id}
    )
    return json.loads(stored)


def _sealed(raw: object, key: str) -> dict:
    assert is_envelope(raw)
    assert SECRET not in json.dumps(raw)
    return CredentialCipher([key]).open(raw)


def test_encrypted_columns_list_matches_the_models():
    """The canary, re-encryption script and migrations walk ENCRYPTED_COLUMNS;
    a new EncryptedJSON column must be added there too."""
    declared = {
        (table.name, column.name)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, EncryptedJSON)
    }
    assert declared == set(ENCRYPTED_COLUMNS)
    assert set(migration.COLUMNS) == declared - {
        ("external_credentials", "credential_data")
    }


# -- telephony_configurations.credentials ---------------------------------------


async def test_telephony_config_route_round_trip(
    db_session, async_session, test_client_factory, encryption_on
):
    org, user = await _org_and_user(async_session)
    async with test_client_factory(user) as client:
        created = await client.post(
            "/api/v1/organizations/telephony-configs",
            json={
                "name": "primary",
                "config": {
                    "provider": "twilio",
                    "account_sid": "AC" + "1" * 32,
                    "auth_token": SECRET,
                    "from_numbers": [],
                },
            },
        )
        assert created.status_code == 200, created.text
        config_id = created.json()["id"]
        assert SECRET not in created.text  # masked in responses as before

        raw = await _raw(
            async_session, "telephony_configurations", "credentials", config_id
        )
        assert _sealed(raw, encryption_on)["auth_token"] == SECRET

        async_session.expunge_all()
        fetched = await client.get(
            f"/api/v1/organizations/telephony-configs/{config_id}"
        )
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["name"] == "primary"

    async_session.expunge_all()
    row = await db_session.get_telephony_configuration_for_org(
        config_id, org.id, active_only=False
    )
    assert row.credentials["auth_token"] == SECRET
    assert row.credentials["account_sid"] == "AC" + "1" * 32


async def test_telephony_lookups_on_encrypted_credentials(
    db_session, async_session, encryption_on
):
    org, _ = await _org_and_user(async_session)
    account_sid = "AC" + uuid.uuid4().hex
    config = await db_session.create_telephony_configuration(
        organization_id=org.id,
        name="twilio",
        provider="twilio",
        credentials={"account_sid": account_sid, "auth_token": SECRET},
    )
    other = await db_session.create_telephony_configuration(
        organization_id=org.id,
        name="twilio-2",
        provider="twilio",
        credentials={"account_sid": "AC-other", "auth_token": SECRET},
    )
    number = "+353 1 555 0199"
    phone = await db_session.create_phone_number(
        organization_id=org.id,
        telephony_configuration_id=config.id,
        address=number,
    )
    await db_session.create_phone_number(
        organization_id=org.id,
        telephony_configuration_id=other.id,
        address="+353 1 555 0198",
    )
    async_session.expunge_all()

    route = await db_session.find_inbound_route_by_account(
        provider="twilio",
        account_id_field="account_sid",
        account_id=account_sid,
        to_number=number,
    )
    assert route is not None
    assert (route[0].id, route[1].id) == (config.id, phone.id)
    assert route[0].credentials["auth_token"] == SECRET
    # The number exists but under another account: no route.
    assert (
        await db_session.find_inbound_route_by_account(
            provider="twilio",
            account_id_field="account_sid",
            account_id="AC-other",
            to_number=number,
        )
        is None
    )

    conflicts = await db_session.find_inbound_routing_conflicts(
        provider="twilio",
        account_id_field="account_sid",
        account_id=account_sid,
        addresses_normalized=[phone.address_normalized],
    )
    assert [(c.id, p.id) for c, p in conflicts] == [(config.id, phone.id)]
    assert (
        await db_session.find_inbound_routing_conflicts(
            provider="twilio",
            account_id_field="account_sid",
            account_id=account_sid,
            addresses_normalized=[phone.address_normalized],
            exclude_configuration_id=config.id,
        )
        == []
    )


async def test_inbound_lookups_skip_undecryptable_candidates(
    db_session, async_session, encryption_on
):
    """One config whose credentials no configured key opens (e.g. sealed
    under a dropped key) must not take inbound routing down for the other
    orgs that share the number."""
    good_org, _ = await _org_and_user(async_session)
    bad_org, _ = await _org_and_user(async_session)
    account_sid = "AC" + uuid.uuid4().hex
    number = f"+353 1 {uuid.uuid4().int % 10_000_000:07d}"
    good = await db_session.create_telephony_configuration(
        organization_id=good_org.id,
        name="good",
        provider="twilio",
        credentials={"account_sid": account_sid, "auth_token": SECRET},
    )
    bad = await db_session.create_telephony_configuration(
        organization_id=bad_org.id,
        name="bad",
        provider="twilio",
        credentials={"account_sid": account_sid, "auth_token": SECRET},
    )
    good_phone = await db_session.create_phone_number(
        organization_id=good_org.id,
        telephony_configuration_id=good.id,
        address=number,
    )
    await db_session.create_phone_number(
        organization_id=bad_org.id,
        telephony_configuration_id=bad.id,
        address=number,
    )
    foreign = CredentialCipher([generate_key()]).seal({"account_sid": account_sid})
    await async_session.execute(
        text("UPDATE telephony_configurations SET credentials = :v WHERE id = :id"),
        {"v": json.dumps(foreign), "id": bad.id},
    )
    async_session.expunge_all()

    route = await db_session.find_inbound_route_by_account(
        provider="twilio",
        account_id_field="account_sid",
        account_id=account_sid,
        to_number=number,
    )
    assert route is not None
    assert (route[0].id, route[1].id) == (good.id, good_phone.id)
    assert route[0].credentials["auth_token"] == SECRET

    conflicts = await db_session.find_inbound_routing_conflicts(
        provider="twilio",
        account_id_field="account_sid",
        account_id=account_sid,
        addresses_normalized=[good_phone.address_normalized],
    )
    assert [(c.id, p.id) for c, p in conflicts] == [(good.id, good_phone.id)]
    assert conflicts[0][0].credentials["auth_token"] == SECRET

    # The cross-org listing behind long-lived provider connections (ARI) too.
    active = {
        c.id: c
        for c in await db_session.list_active_telephony_configurations_by_provider(
            "twilio"
        )
    }
    assert good.id in active and bad.id not in active
    assert active[good.id].credentials["auth_token"] == SECRET


async def test_missing_secret_counts_on_encrypted_credentials(
    db_session, async_session, encryption_on
):
    org, _ = await _org_and_user(async_session)
    for name, creds in [
        ("t-none", {"api_key": SECRET}),
        ("t-empty", {"api_key": SECRET, "webhook_public_key": ""}),
        ("t-set", {"api_key": SECRET, "webhook_public_key": "pk"}),
    ]:
        await db_session.create_telephony_configuration(
            organization_id=org.id, name=name, provider="telnyx", credentials=creds
        )
    await db_session.create_telephony_configuration(
        organization_id=org.id,
        name="v-set",
        provider="vonage",
        credentials={"signature_secret": "s"},
    )
    await db_session.create_telephony_configuration(
        organization_id=org.id,
        name="v-none",
        provider="vonage",
        credentials={"api_key": SECRET},
    )
    async_session.expunge_all()
    assert await db_session.count_telnyx_configs_missing_webhook_public_key(org.id) == 2
    assert await db_session.count_vonage_configs_missing_signature_secret(org.id) == 1


# -- integrations.connection_details -------------------------------------------


async def test_integration_connection_details_round_trip(
    db_session, async_session, encryption_on
):
    org, user = await _org_and_user(async_session)
    integration = await db_session.create_integration(
        integration_id=f"conn-{uuid.uuid4().hex}",
        provider="slack",
        organization_id=org.id,
        connection_details={"access_token": SECRET, "channel": "#calls"},
        created_by=user.id,
    )
    raw = await _raw(
        async_session, "integrations", "connection_details", integration.id
    )
    assert _sealed(raw, encryption_on)["access_token"] == SECRET

    async_session.expunge_all()
    [loaded] = await db_session.get_integrations_by_organization_id(org.id)
    assert loaded.connection_details == {"access_token": SECRET, "channel": "#calls"}

    await db_session.update_integration_connection_details(
        integration.id, {"access_token": "new-" + SECRET}
    )
    raw = await _raw(
        async_session, "integrations", "connection_details", integration.id
    )
    assert _sealed(raw, encryption_on) == {"access_token": "new-" + SECRET}
    async_session.expunge_all()
    [active] = await db_session.get_active_integrations_by_organization(org.id)
    assert active.connection_details == {"access_token": "new-" + SECRET}


# -- organization_configurations.value -------------------------------------------


async def test_org_config_secret_round_trip(db_session, async_session, encryption_on):
    org, _ = await _org_and_user(async_session)
    langfuse_key = OrganizationConfigurationKey.LANGFUSE_CREDENTIALS.value
    value = {
        "host": "https://cloud.langfuse.com",
        "public_key": "pk-lf",
        "secret_key": SECRET,
        "project_id": "p",
    }
    row = await db_session.upsert_configuration(org.id, langfuse_key, value)
    raw = await _raw(async_session, "organization_configurations", "value", row.id)
    assert _sealed(raw, encryption_on) == value

    async_session.expunge_all()
    assert await db_session.get_configuration_value(org.id, langfuse_key) == value
    all_rows = await db_session.get_all_configurations_by_key(langfuse_key)
    assert {"organization_id": org.id, "value": value} in all_rows

    telephony_key = OrganizationConfigurationKey.TELEPHONY_CONFIGURATION.value
    await db_session.upsert_configuration(
        org.id, telephony_key, {"provider": "twilio", "auth_token": SECRET}
    )
    async_session.expunge_all()
    matches = await db_session.get_configurations_by_provider(telephony_key, "twilio")
    assert {
        "organization_id": org.id,
        "value": {"provider": "twilio", "auth_token": SECRET},
    } in matches


async def test_org_config_non_object_value_does_not_break_queries(
    db_session, async_session, encryption_on
):
    """The backfill migration leaves non-dict JSON in plaintext; reading such a
    row returns it as stored instead of failing every query over the table."""
    org, _ = await _org_and_user(async_session)
    key = OrganizationConfigurationKey.LANGFUSE_CREDENTIALS.value
    secret_value = {"secret_key": SECRET}
    await db_session.upsert_configuration(org.id, key, secret_value)
    odd_key = f"legacy-list-{uuid.uuid4().hex}"
    await async_session.execute(
        text(
            "INSERT INTO organization_configurations "
            "(organization_id, key, value, created_at, updated_at) "
            "VALUES (:org, :key, CAST(:value AS json), now(), now())"
        ),
        {"org": org.id, "key": odd_key, "value": json.dumps(["a", 1])},
    )
    async_session.expunge_all()

    rows = {r.key: r.value for r in await db_session.get_all_configurations(org.id)}
    assert rows == {key: secret_value, odd_key: ["a", 1]}
    assert await db_session.get_all_configurations_by_key(odd_key) == [
        {"organization_id": org.id, "value": ["a", 1]}
    ]
    assert await db_session.get_configurations_by_provider(odd_key, "twilio") == []
    assert (
        await db_session.claim_configuration_lease(org.id, odd_key, timedelta(0))
        is None
    )
    assert EncryptedJSON().process_result_value("plain", None) == "plain"


async def test_org_config_lease_works_encrypted(
    db_session, async_session, encryption_on
):
    org, _ = await _org_and_user(async_session)
    lease_key = OrganizationConfigurationKey.ORGANIZATION_BOOTSTRAP.value

    token = await db_session.claim_configuration_lease(
        org.id, lease_key, timedelta(hours=1)
    )
    assert token is not None
    assert (
        await db_session.claim_configuration_lease(
            org.id, lease_key, timedelta(hours=1)
        )
        is None
    )
    row = await db_session.get_configuration(org.id, lease_key)
    assert is_envelope(
        await _raw(async_session, "organization_configurations", "value", row.id)
    )

    # A stale pending lease is taken over; the old holder is fenced out.
    taken = await db_session.claim_configuration_lease(org.id, lease_key, timedelta(0))
    assert taken not in (None, token)
    await db_session.complete_configuration_lease(org.id, lease_key, token)
    async_session.expunge_all()
    assert (await db_session.get_configuration_value(org.id, lease_key))[
        "owner_token"
    ] == taken

    await db_session.release_configuration_lease(org.id, lease_key, taken)
    assert await db_session.get_configuration(org.id, lease_key) is None

    again = await db_session.claim_configuration_lease(org.id, lease_key, timedelta(0))
    await db_session.complete_configuration_lease(org.id, lease_key, again)
    async_session.expunge_all()
    assert await db_session.get_configuration_value(org.id, lease_key) == {
        "status": "completed"
    }
    # Completed is terminal, even once "stale".
    assert (
        await db_session.claim_configuration_lease(org.id, lease_key, timedelta(0))
        is None
    )


# -- re-encryption and startup canary ---------------------------------------------


async def test_reencrypt_and_canary_cover_every_column(
    db_session, async_session, db_connection, monkeypatch, key
):
    org, user = await _org_and_user(async_session)
    monkeypatch.setattr(credential_crypto, "_cipher", None)
    config = await db_session.create_telephony_configuration(
        organization_id=org.id,
        name="plain",
        provider="twilio",
        credentials={"auth_token": SECRET},
    )
    integration = await db_session.create_integration(
        integration_id=f"c-{uuid.uuid4().hex}",
        provider="slack",
        organization_id=org.id,
        connection_details={"access_token": SECRET},
    )
    setting = await db_session.upsert_configuration(
        org.id, "TEST_SECRET", {"api_key": SECRET}
    )
    targets = [
        ("telephony_configurations", "credentials", config.id),
        ("integrations", "connection_details", integration.id),
        ("organization_configurations", "value", setting.id),
    ]
    for table, column, row_id in targets:
        assert SECRET in json.dumps(await _raw(async_session, table, column, row_id))

    client = CredentialEncryptionClient(db_connection)
    report = await client.reencrypt_all(CredentialCipher([key]), batch_size=1)
    assert report.encrypted >= 3
    for table, column, row_id in targets:
        assert SECRET in json.dumps(
            _sealed(await _raw(async_session, table, column, row_id), key)
        )

    # The canary finds an envelope even when external_credentials has none.
    sample = await client.sample_envelope()
    assert sample is not None and is_envelope(sample)


# -- migration -------------------------------------------------------------------


async def _run_migration(db_connection, monkeypatch, step: str) -> None:
    def _run(sync_connection):
        monkeypatch.setattr(
            migration, "op", SimpleNamespace(get_bind=lambda: sync_connection)
        )
        monkeypatch.setattr(migration, "_offline", lambda: False)
        getattr(migration, step)()

    await db_connection.run_sync(_run)


async def _insert_plain_rows(async_session, org, user) -> list[tuple[str, str, int]]:
    config_id = await async_session.scalar(
        text(
            "INSERT INTO telephony_configurations (organization_id, name, provider, "
            "credentials, is_default_outbound, inactive) VALUES (:org, :name, "
            "'twilio', CAST(:data AS json), false, false) RETURNING id"
        ),
        {
            "org": org.id,
            "name": f"m-{uuid.uuid4().hex[:8]}",
            "data": json.dumps({"auth_token": SECRET}),
        },
    )
    integration_id = await async_session.scalar(
        text(
            "INSERT INTO integrations (integration_id, organization_id, provider, "
            "created_by, is_active, connection_details, action) VALUES (:iid, :org, "
            "'slack', :user, true, CAST(:data AS json), 'all_calls') RETURNING id"
        ),
        {
            "iid": uuid.uuid4().hex,
            "org": org.id,
            "user": user.id,
            "data": json.dumps({"access_token": SECRET}),
        },
    )
    setting_id = await async_session.scalar(
        text(
            "INSERT INTO organization_configurations (organization_id, key, value) "
            "VALUES (:org, 'MODEL_CONFIGURATION_V2', CAST(:data AS json)) RETURNING id"
        ),
        {"org": org.id, "data": json.dumps({"llm": {"api_key": SECRET}})},
    )
    await async_session.flush()
    return [
        ("telephony_configurations", "credentials", config_id),
        ("integrations", "connection_details", integration_id),
        ("organization_configurations", "value", setting_id),
    ]


async def test_migration_upgrade_and_downgrade(
    db_session, async_session, db_connection, monkeypatch, key
):
    org, user = await _org_and_user(async_session)
    rows = await _insert_plain_rows(async_session, org, user)
    plain = {r: await _raw(async_session, *r) for r in rows}
    ambient = os.environ.get("CREDENTIALS_ENCRYPTION_KEYS", "")

    # Without keys: no-op.
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEYS", raising=False)
    await _run_migration(db_connection, monkeypatch, "upgrade")
    for r in rows:
        assert await _raw(async_session, *r) == plain[r]

    monkeypatch.setenv(
        "CREDENTIALS_ENCRYPTION_KEYS", ",".join(filter(None, [key, ambient]))
    )
    monkeypatch.setattr(migration, "BATCH_SIZE", 1)
    await _run_migration(db_connection, monkeypatch, "upgrade")
    sealed = {}
    for r in rows:
        sealed[r] = await _raw(async_session, *r)
        assert _sealed(sealed[r], key) == plain[r]

    # The application reads the migrated rows transparently.
    monkeypatch.setattr(credential_crypto, "_cipher", CredentialCipher([key]))
    async_session.expunge_all()
    assert await _app_reads(db_session, org) == (
        {"auth_token": SECRET},
        {"access_token": SECRET},
        {"llm": {"api_key": SECRET}},
    )

    # Idempotent.
    await _run_migration(db_connection, monkeypatch, "upgrade")
    for r in rows:
        assert await _raw(async_session, *r) == sealed[r]

    await _run_migration(db_connection, monkeypatch, "downgrade")
    for r in rows:
        assert await _raw(async_session, *r) == plain[r]


async def _app_reads(db_session, org):
    [config] = await db_session.list_telephony_configurations_by_provider(
        org.id, "twilio", active_only=False
    )
    [integration] = await db_session.get_integrations_by_organization_id(org.id)
    value = await db_session.get_configuration_value(
        org.id, OrganizationConfigurationKey.MODEL_CONFIGURATION_V2.value
    )
    return config.credentials, integration.connection_details, value


async def test_migration_downgrade_refuses_undecryptable_rows(
    async_session, db_connection, monkeypatch, key
):
    org, _ = await _org_and_user(async_session)
    envelope = CredentialCipher([key]).seal({"auth_token": SECRET})
    row_id = await async_session.scalar(
        text(
            "INSERT INTO telephony_configurations (organization_id, name, provider, "
            "credentials, is_default_outbound, inactive) VALUES (:org, 'x', "
            "'twilio', CAST(:data AS json), false, false) RETURNING id"
        ),
        {"org": org.id, "data": json.dumps(envelope)},
    )
    await async_session.flush()
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEYS", raising=False)
    with pytest.raises(RuntimeError, match="cannot be decrypted"):
        await _run_migration(db_connection, monkeypatch, "downgrade")
    assert (
        await _raw(async_session, "telephony_configurations", "credentials", row_id)
        == envelope
    )


@pytest.mark.parametrize("step", ["upgrade", "downgrade"])
def test_migration_offline_mode(monkeypatch, key, step):
    monkeypatch.setattr(migration, "_offline", lambda: True)
    monkeypatch.setattr(migration, "op", None)  # must not touch the database
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEYS", raising=False)
    getattr(migration, step)()
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEYS", key)
    with pytest.raises(RuntimeError, match="reencrypt_credentials"):
        getattr(migration, step)()


# -- CORS ------------------------------------------------------------------------


def test_cors_production_uses_public_base_url_allowlist():
    settings = resolve_cors_settings(
        deployment_mode="oss",
        environment="production",
        allowed_origins=[],
        public_base_url="https://app.lightmove.ai/",
    )
    assert settings.allow_origins == ["https://app.lightmove.ai"]
    assert settings.allow_credentials is True


def test_cors_explicit_allowlist_wins_in_every_mode():
    for mode, environment in [
        ("oss", "production"),
        ("oss", "local"),
        ("saas", "test"),
    ]:
        settings = resolve_cors_settings(
            deployment_mode=mode,
            environment=environment,
            allowed_origins=["https://app.lightmove.ai/", "https://admin.example"],
            public_base_url="https://ignored.example",
        )
        assert settings.allow_origins == [
            "https://app.lightmove.ai",
            "https://admin.example",
        ]
        assert settings.allow_credentials is True


def test_cors_refuses_wildcard_and_missing_production_origin():
    with pytest.raises(CorsConfigurationError, match=r"\*"):
        resolve_cors_settings(
            deployment_mode="oss",
            environment="production",
            allowed_origins=["*"],
            public_base_url="https://app.lightmove.ai",
        )
    with pytest.raises(CorsConfigurationError, match="production"):
        resolve_cors_settings(
            deployment_mode="oss",
            environment="production",
            allowed_origins=[],
            public_base_url=None,
        )
    with pytest.raises(CorsConfigurationError, match="DEPLOYMENT_MODE"):
        resolve_cors_settings(
            deployment_mode="saas",
            environment="local",
            allowed_origins=[],
            public_base_url="https://app.lightmove.ai",
        )


def test_cors_allowlist_entries_are_normalised_like_public_base_url():
    settings = resolve_cors_settings(
        deployment_mode="oss",
        environment="production",
        allowed_origins=["HTTPS://App.LightMove.ai/", " https://admin.example:8443 "],
        public_base_url=None,
    )
    assert settings.allow_origins == [
        "https://app.lightmove.ai",
        "https://admin.example:8443",
    ]
    for bad in ["https://app.lightmove.ai/app", "app.lightmove.ai", "https://x?y=1"]:
        with pytest.raises(CorsConfigurationError, match="not an origin"):
            resolve_cors_settings(
                deployment_mode="oss",
                environment="production",
                allowed_origins=[bad],
                public_base_url=None,
            )


def test_cors_local_oss_stays_open_without_credentials():
    settings = resolve_cors_settings(
        deployment_mode="oss",
        environment="local",
        allowed_origins=[],
        public_base_url=None,
    )
    assert settings.allow_origins == ["*"]
    assert settings.allow_credentials is False


def test_production_cors_still_lets_customer_sites_reach_the_embed_api(monkeypatch):
    """The global allowlist excludes customer sites; the widget's embed
    endpoints answer their preflights themselves."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.testclient import TestClient

    from api.routes.public_embed import PublicEmbedCORSMiddleware, router

    settings = resolve_cors_settings(
        deployment_mode="oss",
        environment="production",
        allowed_origins=[],
        public_base_url="https://app.lightmove.ai",
    )
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allow_origins,
        allow_credentials=settings.allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(PublicEmbedCORSMiddleware, api_prefix="/api/v1")
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)

    customer = "https://shop.customer.example"
    embed = client.options(
        "/api/v1/public/embed/init",
        headers={"Origin": customer, "Access-Control-Request-Method": "POST"},
    )
    assert embed.status_code == 200
    assert embed.headers["access-control-allow-origin"] == customer

    other = client.options(
        "/api/v1/public/download/x",
        headers={"Origin": customer, "Access-Control-Request-Method": "GET"},
    )
    assert other.headers.get("access-control-allow-origin") != customer
    own = client.options(
        "/api/v1/public/download/x",
        headers={
            "Origin": "https://app.lightmove.ai",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert own.headers["access-control-allow-origin"] == "https://app.lightmove.ai"
