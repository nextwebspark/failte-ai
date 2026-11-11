"""Search for, buy and attach LightMove-provided numbers.

The bought number lands in the customer's workspace like any other number: a
row in ``telephony_phone_numbers`` under a telephony configuration. That
configuration is a LightMove-managed one (``credentials.managed_by =
"lightmove"``) holding only the platform account id, so inbound routing, the
webhook signature check and the agent's media stream all run through the
existing provider code unchanged; ``apply_platform_credentials`` adds the
secret when the configuration is loaded.
"""

from datetime import UTC, datetime
from typing import Any, List, Optional

from loguru import logger

from api.db import db_client as default_db_client
from api.db.telephony_configuration_client import TelephonyConfigurationConflictError
from api.services.telephony.inbound_routing import assert_no_inbound_routing_conflict
from api.utils.common import get_backend_endpoints
from api.utils.telephony_address import normalize_telephony_address

from .base import (
    PLATFORM_NUMBER_METADATA_KEY,
    AvailableNumber,
    NumberKind,
    PlatformNumberProvider,
    PlatformNumberProviderError,
    PlatformNumbersNotConfiguredError,
)
from .config import (
    get_platform_number_provider,
    is_managed_configuration,
    platform_numbers_country,
)

MANAGED_CONFIGURATION_NAME = "LightMove numbers"
PLATFORM_NUMBER_LABEL = "LightMove number"


def _require_provider(
    platform: Optional[PlatformNumberProvider],
) -> PlatformNumberProvider:
    platform = platform or get_platform_number_provider()
    if platform is None:
        raise PlatformNumbersNotConfiguredError()
    return platform


async def search_platform_numbers(
    kind: NumberKind,
    *,
    contains: Optional[str] = None,
    limit: int = 10,
    platform: Optional[PlatformNumberProvider] = None,
) -> List[AvailableNumber]:
    provider = _require_provider(platform)
    return await provider.search(
        country=platform_numbers_country(), kind=kind, contains=contains, limit=limit
    )


async def ensure_platform_configuration(
    organization_id: int,
    platform: PlatformNumberProvider,
    *,
    db: Any = default_db_client,
):
    """The org's LightMove-managed configuration, created on first use."""
    existing = await db.list_telephony_configurations_by_provider(
        organization_id, platform.name, active_only=False
    )
    for row in existing:
        credentials = row.credentials or {}
        if (
            is_managed_configuration(credentials)
            and credentials.get("account_sid") == platform.account_id
        ):
            return row

    # Not the default outbound configuration: outbound calls on LightMove's
    # account are a billing decision nobody has made yet.
    for attempt in range(5):
        name = (
            MANAGED_CONFIGURATION_NAME
            if attempt == 0
            else f"{MANAGED_CONFIGURATION_NAME} ({attempt + 1})"
        )
        try:
            return await db.create_telephony_configuration(
                organization_id=organization_id,
                name=name,
                provider=platform.name,
                credentials=platform.configuration_credentials(),
                is_default_outbound=False,
            )
        except TelephonyConfigurationConflictError:
            continue
    raise PlatformNumberProviderError(
        "We couldn't set up your LightMove number. Please contact us.",
        detail=f"no free configuration name for org {organization_id}",
    )


async def record_platform_number_for_billing(
    *, organization_id: int, phone_number_id: int, provider_number_id: str
) -> None:
    """Billing hook for LightMove-provided numbers. Deliberately does nothing.

    TODO(billing): LightMove pays the provider's monthly rent for every number
    bought here. Nothing charges the customer for it yet: no price is shown, no
    Stripe item exists and the billing ledger is untouched. When pricing is
    decided, charge (or start a subscription item) from here; the number is
    identifiable later through ``extra_metadata.lightmove_number`` on its row.
    """
    logger.info(
        f"Platform number {phone_number_id} (provider id {provider_number_id}) "
        f"for org {organization_id} recorded; not billed (no pricing yet)"
    )


async def buy_platform_number(
    *,
    organization_id: int,
    workflow_id: int,
    phone_number: str,
    platform: Optional[PlatformNumberProvider] = None,
    db: Any = default_db_client,
):
    """Buy ``phone_number`` on the platform account and point it at the agent.

    Returns the new ``telephony_phone_numbers`` row. If saving the row fails
    after the purchase, the number is released again so LightMove does not
    keep paying for a number nobody can see.
    """
    provider = _require_provider(platform)
    country = platform_numbers_country()
    normalized = normalize_telephony_address(phone_number, country_hint=country)
    if normalized.address_type != "pstn" or not normalized.canonical.startswith("+"):
        raise ValueError("Pick one of the numbers offered.")

    configuration = await ensure_platform_configuration(
        organization_id, provider, db=db
    )
    await assert_no_inbound_routing_conflict(
        provider=provider.name,
        credentials=configuration.credentials,
        addresses=[normalized.canonical],
        organization_id=organization_id,
        db=db,
    )

    backend_endpoint, _ = await get_backend_endpoints()
    purchased = await provider.buy(
        normalized.canonical,
        voice_url=f"{backend_endpoint}/api/v1/telephony/inbound/run",
        friendly_name=f"LightMove org {organization_id} agent {workflow_id}",
    )

    now = datetime.now(UTC).isoformat()
    try:
        row = await db.create_phone_number(
            organization_id=organization_id,
            telephony_configuration_id=configuration.id,
            address=purchased.phone_number,
            country_code=normalized.country_code or country,
            label=PLATFORM_NUMBER_LABEL,
            inbound_workflow_id=workflow_id,
            extra_metadata={
                PLATFORM_NUMBER_METADATA_KEY: {
                    "provider": provider.name,
                    "provider_number_id": purchased.provider_number_id,
                    "account_id": provider.account_id,
                    "purchased_at": now,
                    "billing": "not_billed",
                },
                "phone_setup": {"method": "new_number", "started_at": now},
            },
        )
    except Exception:
        logger.exception(
            f"Saving bought platform number {purchased.phone_number} failed; "
            "releasing it"
        )
        try:
            await provider.release(purchased.provider_number_id)
        except Exception:
            logger.exception(
                f"Releasing platform number {purchased.provider_number_id} failed; "
                "release it by hand"
            )
        raise

    await record_platform_number_for_billing(
        organization_id=organization_id,
        phone_number_id=row.id,
        provider_number_id=purchased.provider_number_id,
    )
    return row
