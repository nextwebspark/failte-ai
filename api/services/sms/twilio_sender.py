"""Twilio Programmable Messaging over its REST API (no SDK)."""

import httpx

from api.services.sms.base import SmsDeliveryError, SmsMessage
from api.services.sms.settings import TwilioSmsSettings
from api.utils.text import strip_control_characters

_API_BASE = "https://api.twilio.com/2010-04-01"
_MAX_ERROR_DETAIL = 300


class TwilioSmsSender:
    def __init__(
        self,
        settings: TwilioSmsSettings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        # Tests pass an httpx.MockTransport; production uses the network.
        self._transport = transport

    @property
    def delivers(self) -> bool:
        return True

    async def send(self, message: SmsMessage) -> None:
        s = self._settings
        url = f"{_API_BASE}/Accounts/{s.account_sid}/Messages.json"
        data = {"To": message.to, "From": s.from_, "Body": message.body}
        try:
            async with httpx.AsyncClient(
                timeout=s.timeout_seconds, transport=self._transport
            ) as client:
                response = await client.post(
                    url,
                    data=data,
                    auth=(s.account_sid, s.auth_token.get_secret_value()),
                )
        except httpx.HTTPError as exc:
            raise SmsDeliveryError(
                f"Twilio request failed: {type(exc).__name__}"
            ) from exc
        if response.status_code >= 400:
            # Twilio explains rejections in the body (unverified number in a
            # trial account, unsupported sender id for the country, ...).
            detail = strip_control_characters(response.text)
            raise SmsDeliveryError(
                f"Twilio rejected the message (HTTP {response.status_code}): "
                f"{detail[:_MAX_ERROR_DETAIL]}"
            )
