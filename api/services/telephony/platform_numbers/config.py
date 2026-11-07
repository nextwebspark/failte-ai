"""Which platform-number provider this deployment runs, and its credentials.

Kept free of database imports: the telephony factory calls
``apply_platform_credentials`` every time it loads a configuration.
"""

from typing import Any, Dict, Mapping, Optional

from api import constants

from .base import MANAGED_BY_KEY, MANAGED_BY_LIGHTMOVE, PLATFORM_NUMBER_METADATA_KEY
from .twilio import TwilioPlatformNumbers


def get_platform_number_provider() -> Optional[TwilioPlatformNumbers]:
    """The configured provider, or None when LightMove numbers are switched off.

    Twilio is the only provider today; another one plugs in here behind the
    same ``PlatformNumberProvider`` shape.
    """
    if constants.PLATFORM_TWILIO_ACCOUNT_SID and constants.PLATFORM_TWILIO_AUTH_TOKEN:
        return TwilioPlatformNumbers(
            constants.PLATFORM_TWILIO_ACCOUNT_SID,
            constants.PLATFORM_TWILIO_AUTH_TOKEN,
            bundle_sid=constants.PLATFORM_TWILIO_BUNDLE_SID,
            address_sid=constants.PLATFORM_TWILIO_ADDRESS_SID,
        )
    return None


def platform_numbers_country() -> str:
    return constants.PLATFORM_NUMBERS_COUNTRY


def is_managed_configuration(credentials: Optional[Mapping[str, Any]]) -> bool:
    return (credentials or {}).get(MANAGED_BY_KEY) == MANAGED_BY_LIGHTMOVE


def is_platform_number(extra_metadata: Optional[Mapping[str, Any]]) -> bool:
    return isinstance((extra_metadata or {}).get(PLATFORM_NUMBER_METADATA_KEY), dict)


def apply_platform_credentials(
    provider_name: str, raw: Dict[str, Any]
) -> Dict[str, Any]:
    """Fill in the platform secret on a LightMove-managed configuration.

    Only when the row is marked managed, is for the platform provider, and names
    the platform account. A managed row left over from a rotated or removed
    account gets nothing, so its calls fail closed instead of running on a
    different account.
    """
    if not is_managed_configuration(raw):
        return raw
    platform = get_platform_number_provider()
    if platform is None or platform.name != provider_name:
        return raw
    if raw.get("account_sid") != platform.account_id:
        return raw
    return {**raw, **platform.runtime_credentials()}
