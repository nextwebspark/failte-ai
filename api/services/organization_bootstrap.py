"""Once-per-organization provisioning of model services and managed SIP.

Bootstrapping writes the organization's v2 model configuration and provisions
owner-scoped managed SIP connectivity. With platform models enabled the
configuration is the platform default and nothing is minted; otherwise it holds
a freshly minted MPS service key.
Service-key minting is not idempotent upstream — ``create_service_key`` is a
plain POST — so concurrent callers must not both run it.

Entry is therefore guarded two ways: the organization's own configuration state
decides whether work is needed at all, and a database lease decides which
single caller performs it. Keying on state rather than on a create-time flag is
what makes a failed attempt retryable; the lease is what keeps the retry from
racing itself.
"""

from datetime import timedelta

from loguru import logger

from api.constants import (
    AUTH_PROVIDER,
    DEPLOYMENT_MODE,
    MANAGED_SIP_PROVISIONING_ENABLED,
    PLATFORM_MODELS_ENABLED,
)
from api.db import db_client
from api.db.organization_configuration_client import LEASE_COMPLETED
from api.enums import OrganizationConfigurationKey
from api.errors.mps import MPSUnavailableError
from api.schemas.ai_model_configuration import (
    DograhManagedAIModelConfiguration,
    OrganizationAIModelConfigurationV2,
)
from api.schemas.platform_models import default_platform_configuration
from api.services.configuration.ai_model_configuration import (
    has_organization_ai_model_configuration_v2,
    upsert_organization_ai_model_configuration_v2,
)
from api.services.mps_billing import ensure_hosted_mps_billing_account_v2
from api.services.mps_service_key_client import mps_service_key_client

MANAGED_SERVICE_KEY_NAME = "Default Fallcha.ai Model Service Key"

# A holder that dies mid-provisioning leaves its lease pending. This bounds how
# long the organization waits before another request is allowed to take over.
BOOTSTRAP_LEASE_STALE_AFTER = timedelta(minutes=5)

_BOOTSTRAP_KEY = OrganizationConfigurationKey.ORGANIZATION_BOOTSTRAP.value


async def ensure_organization_bootstrapped(
    organization_id: int,
    *,
    created_by: str,
) -> bool:
    """Ensure an organization has its model configuration and managed SIP.

    Cheap enough to call on every authenticated request: an organization that
    has completed bootstrap costs a single indexed read. Returns True when the
    organization is fully provisioned.

    Each piece is claimed against its own state, never against a create-time
    flag, so this both completes a half-finished bootstrap and backfills
    organizations that predate a piece — an existing org with a model
    configuration but no SIP gets SIP on its owner's next sign-in without
    depending on which model-service key it currently uses.

    Never raises. A provisioning failure must not fail authentication — the
    caller is a legitimately authenticated user either way.
    """
    if await _is_bootstrap_complete(organization_id):
        return True

    # Presence, not validity: a stored configuration that fails to parse (for
    # example one written by a newer release during a rolling deploy) must not
    # be overwritten with a freshly provisioned one.
    has_configuration = await has_organization_ai_model_configuration_v2(
        organization_id
    )
    # With managed SIP off the sentinel completes without it, so turning the
    # flag on later does not backfill existing organizations.
    sip_provisioned = (
        not MANAGED_SIP_PROVISIONING_ENABLED
        or await _has_managed_sip_connectivity(organization_id)
    )

    owner_token = await db_client.claim_configuration_lease(
        organization_id,
        _BOOTSTRAP_KEY,
        BOOTSTRAP_LEASE_STALE_AFTER,
    )
    if owner_token is None:
        # Another request holds the lease and is provisioning right now.
        return False

    if has_configuration and sip_provisioned:
        # Provisioned before the sentinel existed. Record it so subsequent
        # requests take the single-read fast path above.
        await db_client.complete_configuration_lease(
            organization_id, _BOOTSTRAP_KEY, owner_token
        )
        return True

    try:
        complete = await _bootstrap_organization(
            organization_id,
            created_by=created_by,
            has_configuration=has_configuration,
            sip_provisioned=sip_provisioned,
        )
    except Exception:
        await db_client.release_configuration_lease(
            organization_id, _BOOTSTRAP_KEY, owner_token
        )
        logger.warning(
            "Failed to bootstrap organization {}; will retry on a later request",
            organization_id,
            exc_info=True,
        )
        return False

    if not complete:
        # Deliberately leave the lease pending rather than releasing it: the
        # model configuration is persisted, so only SIP is outstanding, and the
        # staleness window throttles retries instead of re-attempting a failing
        # provider on every single request.
        return False

    await db_client.complete_configuration_lease(
        organization_id, _BOOTSTRAP_KEY, owner_token
    )
    return True


async def _is_bootstrap_complete(organization_id: int) -> bool:
    row = await db_client.get_configuration(organization_id, _BOOTSTRAP_KEY)
    return bool(row and (row.value or {}).get("status") == LEASE_COMPLETED)


async def _has_managed_sip_connectivity(organization_id: int) -> bool:
    from api.services.telephony.providers.cloudonix.provisioning import (
        has_managed_cloudonix_configuration,
    )

    return await has_managed_cloudonix_configuration(organization_id)


async def _bootstrap_organization(
    organization_id: int,
    *,
    created_by: str,
    has_configuration: bool,
    sip_provisioned: bool,
) -> bool:
    """Provision whatever the organization is missing.

    Returns True when the organization ends up fully provisioned, i.e. when the
    lease may be marked terminal.
    """
    if not has_configuration and PLATFORM_MODELS_ENABLED:
        # Platform models run on the operator's Vertex project: no key to mint
        # and no MPS billing account to open.
        await upsert_organization_ai_model_configuration_v2(
            organization_id,
            OrganizationAIModelConfigurationV2(
                mode="platform", platform=default_platform_configuration()
            ),
        )
    elif not has_configuration:
        # Billing is best effort: it is recoverable out of band, and failing the
        # whole bootstrap over it would also cost the org its model config.
        try:
            await ensure_hosted_mps_billing_account_v2(
                organization_id,
                created_by=created_by,
            )
        except Exception:
            logger.warning(
                "Failed to initialize hosted MPS billing account for organization {}",
                organization_id,
                exc_info=True,
            )

        configuration = await provision_dograh_managed_model_configuration(
            organization_id,
            created_by=created_by,
        )
        # Persist before provisioning SIP: the service key is already issued and
        # minting is not idempotent, so the shorter the window in which a crash
        # can lose it, the fewer orphaned keys a retry leaves behind.
        await upsert_organization_ai_model_configuration_v2(
            organization_id, configuration
        )

    if sip_provisioned:
        return True

    return await provision_managed_sip_connectivity(
        organization_id,
        created_by=created_by,
    )


async def provision_dograh_managed_model_configuration(
    organization_id: int,
    *,
    created_by: str,
) -> OrganizationAIModelConfigurationV2:
    """Mint an organization's MPS service key and build its model configuration.

    Returns the configuration without persisting it; the caller owns that. Has
    no side effects beyond the key mint — SIP connectivity is provisioned
    separately by ``provision_managed_sip_connectivity``.
    """
    data = await mps_service_key_client.create_service_key(
        name=MANAGED_SERVICE_KEY_NAME,
        description=(
            "Auto-generated key for OSS user"
            if AUTH_PROVIDER == "local"
            else f"Auto-generated key for organization {organization_id}"
        ),
        organization_id=(None if AUTH_PROVIDER == "local" else organization_id),
        created_by=created_by,
        expires_in_days=90,
    )
    service_key = data.get("service_key")
    if not service_key:
        raise MPSUnavailableError("create_service_key")

    return OrganizationAIModelConfigurationV2(
        mode="dograh",
        dograh=DograhManagedAIModelConfiguration(api_key=service_key),
    )


async def provision_managed_sip_connectivity(
    organization_id: int,
    *,
    created_by: str,
) -> bool:
    """Provision the organization's Dograh-managed SIP connectivity.

    MPS owns the Cloudonix domain. OSS allocations are owned by ``created_by``;
    hosted allocations are owned by ``organization_id``. Model configuration
    and service-key rotation do not affect that identity.

    Best effort by design, returning whether it succeeded: a telephony provider
    outage must not fail authentication or discard independently provisioned
    model configuration.
    """
    try:
        from api.services.telephony.providers.cloudonix.provisioning import (
            ensure_managed_cloudonix_configuration,
        )

        await ensure_managed_cloudonix_configuration(
            organization_id,
            mps_organization_id=(None if DEPLOYMENT_MODE == "oss" else organization_id),
            created_by=created_by,
        )
    except Exception:
        logger.error(
            "Failed to provision managed Cloudonix SIP connectivity for "
            "organization {}",
            organization_id,
            exc_info=True,
        )
        return False
    return True
