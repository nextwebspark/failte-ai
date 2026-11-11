"""Types shared by every platform-number provider.

A *platform number* is a phone number LightMove buys on its own provider
account and attaches to a customer's agent, as opposed to a number on a provider
account the customer connected themselves. The provider is pluggable; Twilio is
the first one.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Protocol

NumberKind = Literal["local", "mobile"]

# Marks a telephony configuration that LightMove manages. The row stores only
# the account id (inbound routing matches on it) plus this marker; the secret
# is added from the environment each time the configuration is loaded, so it is
# never copied into customer rows and rotates with the deployment.
MANAGED_BY_KEY = "managed_by"
MANAGED_BY_LIGHTMOVE = "lightmove"

# Key under ``telephony_phone_numbers.extra_metadata`` recording that LightMove
# owns the number on its provider account, so it can be released and billed
# later. Holds the provider, its id for the number and when it was bought.
PLATFORM_NUMBER_METADATA_KEY = "lightmove_number"


class PlatformNumbersNotConfiguredError(RuntimeError):
    """LightMove-provided numbers are switched off on this deployment."""

    def __init__(self) -> None:
        super().__init__(
            "LightMove numbers aren't available yet. Ask us and we'll set one "
            "up for you, or use your own phone provider account."
        )


class PlatformNumberProviderError(RuntimeError):
    """The provider refused or failed a search, purchase or release.

    ``message`` is safe to show a customer; ``detail`` is for logs and never
    contains credentials.
    """

    def __init__(self, message: str, *, detail: str = "", status: int = 0) -> None:
        super().__init__(message)
        self.detail = detail
        self.status = status


@dataclass(frozen=True)
class AvailableNumber:
    phone_number: str  # E.164
    friendly_name: str
    kind: NumberKind
    locality: Optional[str] = None
    region: Optional[str] = None
    # What the provider says it needs on file before this number can be bought
    # ("none", "any", "local", "foreign" on Twilio).
    address_requirements: Optional[str] = None


@dataclass(frozen=True)
class PurchasedNumber:
    phone_number: str  # E.164
    provider_number_id: str  # e.g. Twilio IncomingPhoneNumber SID (PN...)


class PlatformNumberProvider(Protocol):
    """What LightMove needs from a provider to hand out numbers."""

    #: Telephony provider registry name the bought numbers run on.
    name: str
    #: The platform account id, as stored in ``credentials[account_id_field]``.
    account_id: str

    async def search(
        self, *, country: str, kind: NumberKind, contains: Optional[str], limit: int
    ) -> List[AvailableNumber]: ...

    async def buy(
        self, phone_number: str, *, voice_url: str, friendly_name: str
    ) -> PurchasedNumber: ...

    async def release(self, provider_number_id: str) -> None: ...

    def configuration_credentials(self) -> Dict[str, Any]:
        """What a customer's managed configuration row stores (no secrets)."""
        ...

    def runtime_credentials(self) -> Dict[str, Any]:
        """Secrets merged in when that configuration is loaded."""
        ...
