"""Transport-agnostic email contract."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str
    # Lets a transport that supports it drop a resend of the same message.
    idempotency_key: str | None = None


class EmailDeliveryError(Exception):
    """The transport could not hand the message off for delivery.

    ``retryable`` is False when another attempt soon would fail the same way:
    the provider is down or timing out, or it rejected this message.
    """

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class EmailSender(Protocol):
    @property
    def delivers(self) -> bool:
        """True when messages actually leave this process (not just logged)."""
        ...

    async def send(self, message: EmailMessage) -> None:
        """Send ``message`` or raise ``EmailDeliveryError``."""
        ...
