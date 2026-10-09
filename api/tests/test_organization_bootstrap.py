from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.db.organization_configuration_client import LEASE_COMPLETED, LEASE_PENDING
from api.services import organization_bootstrap as bootstrap

ORG_ID = 42
CREATED_BY = "provider-user"
MINTED_KEY = "minted-svc-key"
LEASE_OWNER_TOKEN = "lease-owner-token"


@pytest.fixture(autouse=True)
def sentinel(monkeypatch):
    """Bootstrap sentinel row; absent by default. Autouse so no test hits the DB."""
    state = SimpleNamespace(row=None)
    monkeypatch.setattr(
        bootstrap.db_client,
        "get_configuration",
        AsyncMock(side_effect=lambda *_: state.row),
    )
    return state


@pytest.fixture(autouse=True)
def sip_present(monkeypatch):
    """Whether managed SIP already exists; False by default."""
    mock = AsyncMock(return_value=False)
    monkeypatch.setattr(bootstrap, "_has_managed_sip_connectivity", mock)
    return mock


@pytest.fixture(autouse=True)
def sip(monkeypatch):
    """Provisioning of managed SIP. Autouse so no test reaches a real provider."""
    mock = AsyncMock(return_value=True)
    monkeypatch.setattr(bootstrap, "provision_managed_sip_connectivity", mock)
    return mock


@pytest.fixture(autouse=True)
def flags(monkeypatch):
    """Deployment flags at their MPS defaults, independent of the environment."""
    monkeypatch.setattr(bootstrap, "PLATFORM_MODELS_ENABLED", False)
    monkeypatch.setattr(bootstrap, "MANAGED_SIP_PROVISIONING_ENABLED", True)


@pytest.fixture
def config(monkeypatch):
    """Whether the org has a stored v2 model configuration; absent by default."""
    mock = AsyncMock(return_value=False)
    monkeypatch.setattr(bootstrap, "has_organization_ai_model_configuration_v2", mock)
    return mock


@pytest.fixture
def lease(monkeypatch):
    calls = SimpleNamespace(
        claim=AsyncMock(return_value=LEASE_OWNER_TOKEN),
        complete=AsyncMock(),
        release=AsyncMock(),
    )
    monkeypatch.setattr(bootstrap.db_client, "claim_configuration_lease", calls.claim)
    monkeypatch.setattr(
        bootstrap.db_client, "complete_configuration_lease", calls.complete
    )
    monkeypatch.setattr(
        bootstrap.db_client, "release_configuration_lease", calls.release
    )
    return calls


@pytest.fixture
def mps(monkeypatch):
    create_service_key = AsyncMock(return_value={"service_key": MINTED_KEY})
    monkeypatch.setattr(
        bootstrap.mps_service_key_client, "create_service_key", create_service_key
    )
    monkeypatch.setattr(bootstrap, "ensure_hosted_mps_billing_account_v2", AsyncMock())
    return create_service_key


@pytest.fixture
def upsert(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(
        bootstrap, "upsert_organization_ai_model_configuration_v2", mock
    )
    return mock


@pytest.mark.asyncio
async def test_completed_sentinel_short_circuits(
    sentinel, config, lease, mps, upsert, sip
):
    """The settled case must cost one read and touch nothing else."""
    sentinel.row = SimpleNamespace(value={"status": LEASE_COMPLETED})

    assert await bootstrap.ensure_organization_bootstrapped(
        ORG_ID, created_by=CREATED_BY
    )

    config.assert_not_awaited()
    lease.claim.assert_not_awaited()
    mps.assert_not_awaited()
    sip.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_sentinel_does_not_short_circuit(
    sentinel, config, lease, mps, upsert, sip, sip_present
):
    """Only a terminal sentinel means done; a pending one is work in progress."""
    sentinel.row = SimpleNamespace(value={"status": LEASE_PENDING})
    config.return_value = True

    await bootstrap.ensure_organization_bootstrapped(ORG_ID, created_by=CREATED_BY)

    lease.claim.assert_awaited_once()


@pytest.mark.asyncio
async def test_fully_provisioned_org_backfills_the_sentinel(
    config, lease, mps, upsert, sip, sip_present
):
    """Orgs provisioned before the sentinel existed must reach the fast path."""
    config.return_value = True
    sip_present.return_value = True

    assert await bootstrap.ensure_organization_bootstrapped(
        ORG_ID, created_by=CREATED_BY
    )

    lease.claim.assert_awaited_once()
    mps.assert_not_awaited()
    sip.assert_not_awaited()
    lease.complete.assert_awaited_once_with(
        ORG_ID, bootstrap._BOOTSTRAP_KEY, LEASE_OWNER_TOKEN
    )


@pytest.mark.asyncio
async def test_existing_org_gets_owner_scoped_sip_without_minting_a_second_key(
    config, lease, mps, upsert, sip
):
    """The backfill case: model config already exists, SIP does not.

    Re-minting would strand the org's current key and issue a second billable
    one. SIP is independent and uses the bootstrap owner's identity.
    """
    config.return_value = True

    assert await bootstrap.ensure_organization_bootstrapped(
        ORG_ID, created_by=CREATED_BY
    )

    mps.assert_not_awaited()
    upsert.assert_not_awaited()
    sip.assert_awaited_once_with(ORG_ID, created_by=CREATED_BY)
    lease.complete.assert_awaited_once_with(
        ORG_ID, bootstrap._BOOTSTRAP_KEY, LEASE_OWNER_TOKEN
    )


@pytest.mark.asyncio
async def test_new_org_mints_key_and_independently_provisions_sip(
    config, lease, mps, upsert, sip
):
    assert await bootstrap.ensure_organization_bootstrapped(
        ORG_ID, created_by=CREATED_BY
    )

    mps.assert_awaited_once()
    configuration = upsert.await_args.args[1]
    assert configuration.mode == "dograh"
    assert configuration.dograh.api_key == MINTED_KEY
    sip.assert_awaited_once_with(ORG_ID, created_by=CREATED_BY)
    lease.complete.assert_awaited_once_with(
        ORG_ID, bootstrap._BOOTSTRAP_KEY, LEASE_OWNER_TOKEN
    )


@pytest.mark.asyncio
async def test_losing_the_lease_skips_provisioning(config, lease, mps, upsert, sip):
    """A concurrent request already holds it; minting again would duplicate keys."""
    lease.claim.return_value = None

    assert not await bootstrap.ensure_organization_bootstrapped(
        ORG_ID, created_by=CREATED_BY
    )

    mps.assert_not_awaited()
    upsert.assert_not_awaited()
    sip.assert_not_awaited()
    lease.complete.assert_not_awaited()
    lease.release.assert_not_awaited()


@pytest.mark.asyncio
async def test_key_mint_failure_releases_the_lease(config, lease, mps, upsert, sip):
    """Nothing was persisted, so the next request should retry immediately."""
    mps.side_effect = RuntimeError("MPS down")

    assert not await bootstrap.ensure_organization_bootstrapped(
        ORG_ID, created_by=CREATED_BY
    )

    upsert.assert_not_awaited()
    lease.release.assert_awaited_once_with(
        ORG_ID, bootstrap._BOOTSTRAP_KEY, LEASE_OWNER_TOKEN
    )
    lease.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_service_key_is_treated_as_failure(config, lease, mps, upsert):
    """A 200 with no key must not mark the org bootstrapped and never retry."""
    mps.return_value = {}

    assert not await bootstrap.ensure_organization_bootstrapped(
        ORG_ID, created_by=CREATED_BY
    )

    upsert.assert_not_awaited()
    lease.release.assert_awaited_once_with(
        ORG_ID, bootstrap._BOOTSTRAP_KEY, LEASE_OWNER_TOKEN
    )
    lease.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_sip_failure_leaves_the_lease_pending_for_a_throttled_retry(
    config, lease, mps, upsert, sip
):
    """The config is persisted, so releasing would retry a failing provider on
    every request; the staleness window should pace it instead."""
    config.return_value = True
    sip.return_value = False

    assert not await bootstrap.ensure_organization_bootstrapped(
        ORG_ID, created_by=CREATED_BY
    )

    lease.complete.assert_not_awaited()
    lease.release.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_org_keeps_its_configuration_when_sip_fails(
    config, lease, mps, upsert, sip
):
    sip.return_value = False

    assert not await bootstrap.ensure_organization_bootstrapped(
        ORG_ID, created_by=CREATED_BY
    )

    upsert.assert_awaited_once()
    lease.release.assert_not_awaited()


@pytest.mark.asyncio
async def test_byok_org_still_gets_owner_scoped_sip(config, lease, mps, upsert, sip):
    """SIP ownership is independent of the organization's model configuration."""
    config.return_value = True

    assert await bootstrap.ensure_organization_bootstrapped(
        ORG_ID, created_by=CREATED_BY
    )

    mps.assert_not_awaited()
    sip.assert_awaited_once_with(ORG_ID, created_by=CREATED_BY)
    lease.complete.assert_awaited_once_with(
        ORG_ID, bootstrap._BOOTSTRAP_KEY, LEASE_OWNER_TOKEN
    )


@pytest.mark.asyncio
async def test_billing_failure_does_not_discard_the_model_configuration(
    monkeypatch, config, lease, mps, upsert, sip
):
    monkeypatch.setattr(
        bootstrap,
        "ensure_hosted_mps_billing_account_v2",
        AsyncMock(side_effect=RuntimeError("billing down")),
    )

    assert await bootstrap.ensure_organization_bootstrapped(
        ORG_ID, created_by=CREATED_BY
    )

    upsert.assert_awaited_once()
    lease.complete.assert_awaited_once_with(
        ORG_ID, bootstrap._BOOTSTRAP_KEY, LEASE_OWNER_TOKEN
    )


@pytest.mark.asyncio
async def test_platform_org_starts_on_the_platform_default_without_mps(
    monkeypatch, config, lease, mps, upsert, sip
):
    monkeypatch.setattr(bootstrap, "PLATFORM_MODELS_ENABLED", True)
    billing = AsyncMock()
    monkeypatch.setattr(bootstrap, "ensure_hosted_mps_billing_account_v2", billing)

    assert await bootstrap.ensure_organization_bootstrapped(
        ORG_ID, created_by=CREATED_BY
    )

    mps.assert_not_awaited()
    billing.assert_not_awaited()
    configuration = upsert.await_args.args[1]
    assert configuration.mode == "platform"
    assert configuration.platform.pipeline_mode == "realtime"
    assert configuration.platform.realtime.voice == "Charon"
    assert configuration.platform.realtime.language == "en"
    lease.complete.assert_awaited_once_with(
        ORG_ID, bootstrap._BOOTSTRAP_KEY, LEASE_OWNER_TOKEN
    )


@pytest.mark.asyncio
async def test_disabled_managed_sip_is_never_provisioned(
    monkeypatch, config, lease, mps, upsert, sip, sip_present
):
    monkeypatch.setattr(bootstrap, "PLATFORM_MODELS_ENABLED", True)
    monkeypatch.setattr(bootstrap, "MANAGED_SIP_PROVISIONING_ENABLED", False)

    assert await bootstrap.ensure_organization_bootstrapped(
        ORG_ID, created_by=CREATED_BY
    )

    sip_present.assert_not_awaited()
    sip.assert_not_awaited()
    lease.complete.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [False, True])
async def test_stored_configuration_is_never_reprovisioned(
    monkeypatch, platform, config, lease, mps, upsert, sip
):
    """A stored row that this release cannot parse (a rolling deploy) still
    counts as configured: replacing it would discard the org's choices and,
    on MPS, mint a second key."""
    monkeypatch.setattr(bootstrap, "PLATFORM_MODELS_ENABLED", platform)
    config.return_value = True

    assert await bootstrap.ensure_organization_bootstrapped(
        ORG_ID, created_by=CREATED_BY
    )

    mps.assert_not_awaited()
    upsert.assert_not_awaited()
