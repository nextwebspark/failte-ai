"""Transport-agnostic email contract."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str


class EmailDeliveryError(Exception):
    """The transport could not hand the message off for delivery."""


class EmailSender(Protocol):
    @property
    def delivers(self) -> bool:
        """True when messages actually leave this process (not just logged)."""
        ...

    async def send(self, message: EmailMessage) -> None:
        """Send ``message`` or raise ``EmailDeliveryError``."""
        ...
