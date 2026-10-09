import aiohttp
from pydantic import SecretStr

from api.services.email.base import EmailDeliveryError, EmailMessage
from api.utils.text import strip_control_characters

_RESEND_URL = "https://api.resend.com/emails"
_TIMEOUT = aiohttp.ClientTimeout(total=15)
_MAX_ERROR_DETAIL = 300


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
            "subject": strip_control_characters(message.subject),
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
                    # Resend explains rejections in the body (unverified domain,
                    # sandbox recipient limit, bad key); keep it for the logs.
                    detail = strip_control_characters(await response.text())
                    raise EmailDeliveryError(
                        f"Resend rejected the message (HTTP {response.status}): "
                        f"{detail[:_MAX_ERROR_DETAIL]}"
                    )
        except aiohttp.ClientError as exc:
            raise EmailDeliveryError(f"Resend request failed: {exc}") from exc
