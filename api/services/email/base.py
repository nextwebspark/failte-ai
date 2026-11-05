"""Transport-agnostic email contract."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


@dataclass(frozen=True, slots=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str
    # Lets a transport that supports it drop a resend of the same message.
    idempotency_key: str | None = None


class EmailFailure(StrEnum):
    """How worthwhile another attempt at the same message is."""

    # A rate limit or a dropped connection: likely to clear soon.
    TRANSIENT = "transient"
    # The provider answered with a server error: worth one more try.
    PROVIDER_ERROR = "provider_error"
    # A timeout, bad credentials or a rejected message: another attempt soon
    # fails the same way.
    FINAL = "final"


class EmailDeliveryError(Exception):
    """The transport could not hand the message off for delivery."""

    def __init__(
        self, message: str, *, failure: EmailFailure = EmailFailure.TRANSIENT
    ) -> None:
        super().__init__(message)
        self.failure = failure


class EmailSender(Protocol):
    @property
    def delivers(self) -> bool:
        """True when messages actually leave this process (not just logged)."""
        ...

    async def send(self, message: EmailMessage) -> None:
        """Send ``message`` or raise ``EmailDeliveryError``."""
        ...
