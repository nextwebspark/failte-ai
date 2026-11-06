"""Transport-agnostic text message (SMS) contract, mirroring api.services.email."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SmsMessage:
    # E.164, e.g. +353871234567.
    to: str
    body: str


class SmsDeliveryError(Exception):
    """The provider could not accept the message for delivery."""


class SmsSender(Protocol):
    @property
    def delivers(self) -> bool:
        """True when messages actually leave this process (not just logged)."""
        ...

    async def send(self, message: SmsMessage) -> None:
        """Send ``message`` or raise ``SmsDeliveryError``."""
        ...
