import aiohttp
from pydantic import SecretStr

from api.services.email.base import EmailDeliveryError, EmailMessage

_RESEND_URL = "https://api.resend.com/emails"
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class ResendEmailSender:
    def __init__(self, api_key: SecretStr, from_address: str) -> None:
        self._api_key = api_key
        self._from = from_address

    @property
    def delivers(self) -> bool:
        return True

    async def send(self, message: EmailMessage) -> None:
        payload = {
            "from": self._from,
            "to": [message.to],
            "subject": message.subject,
            "text": message.text,
            "html": message.html,
        }
        headers = {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
        try:
            async with (
                aiohttp.ClientSession(timeout=_TIMEOUT) as session,
                session.post(_RESEND_URL, json=payload, headers=headers) as response,
            ):
                if response.status >= 400:
                    raise EmailDeliveryError(
                        f"Resend rejected the message (HTTP {response.status})"
                    )
        except aiohttp.ClientError as exc:
            raise EmailDeliveryError(f"Resend request failed: {exc}") from exc
