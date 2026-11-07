"""LightMove-provided phone numbers.

LightMove buys a number on its own provider account and attaches it to a
customer's agent. The purchase flow lives in ``service`` (it touches the
database); this package root only exposes the light pieces the telephony
factory needs.
"""

from .base import (
    MANAGED_BY_KEY,
    MANAGED_BY_LIGHTMOVE,
    PLATFORM_NUMBER_METADATA_KEY,
    AvailableNumber,
    NumberKind,
    PlatformNumberProvider,
    PlatformNumberProviderError,
    PlatformNumbersNotConfiguredError,
    PurchasedNumber,
)
from .config import (
    apply_platform_credentials,
    get_platform_number_provider,
    is_managed_configuration,
    is_platform_number,
    platform_numbers_country,
)

__all__ = [
    "MANAGED_BY_KEY",
    "MANAGED_BY_LIGHTMOVE",
    "PLATFORM_NUMBER_METADATA_KEY",
    "AvailableNumber",
    "NumberKind",
    "PlatformNumberProvider",
    "PlatformNumberProviderError",
    "PlatformNumbersNotConfiguredError",
    "PurchasedNumber",
    "apply_platform_credentials",
    "get_platform_number_provider",
    "is_managed_configuration",
    "is_platform_number",
    "platform_numbers_country",
]
