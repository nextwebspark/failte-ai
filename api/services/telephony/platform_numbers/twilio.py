"""Twilio as a platform-number provider.

Uses three REST resources on LightMove's own account:

* ``GET  /AvailablePhoneNumbers/{country}/{Local|Mobile}.json`` to search,
* ``POST /IncomingPhoneNumbers.json`` to buy (with the inbound VoiceUrl set in
  the same request, so the number rings the agent straight away),
* ``DELETE /IncomingPhoneNumbers/{sid}.json`` to release.

Never exercised against the real Twilio API from this codebase's tests; the
request and response shapes follow Twilio's published REST reference.
"""

from typing import Any, Callable, Dict, List, Optional

import aiohttp
from loguru import logger

from .base import (
    MANAGED_BY_KEY,
    MANAGED_BY_LIGHTMOVE,
    AvailableNumber,
    NumberKind,
    PlatformNumberProviderError,
    PurchasedNumber,
)

_API = "https://api.twilio.com/2010-04-01"
_KIND_RESOURCE = {"local": "Local", "mobile": "Mobile"}
_TIMEOUT = aiohttp.ClientTimeout(total=20)


def _twilio_message(body: Any) -> str:
    if isinstance(body, dict):
        code = body.get("code")
        message = body.get("message") or ""
        return f"{code}: {message}" if code else str(message)
    return str(body)[:500]


class TwilioPlatformNumbers:
    name = "twilio"

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        *,
        bundle_sid: str = "",
        address_sid: str = "",
        session_factory: Optional[Callable[[], aiohttp.ClientSession]] = None,
    ) -> None:
        self.account_id = account_sid
        self._auth_token = auth_token
        self._bundle_sid = bundle_sid
        self._address_sid = address_sid
        self._session_factory = session_factory or (
            lambda: aiohttp.ClientSession(timeout=_TIMEOUT)
        )
        self._base = f"{_API}/Accounts/{account_sid}"

    def __repr__(self) -> str:  # never print the token
        return f"TwilioPlatformNumbers(account_sid={self.account_id!r})"

    def _auth(self) -> aiohttp.BasicAuth:
        return aiohttp.BasicAuth(self.account_id, self._auth_token)

    async def search(
        self,
        *,
        country: str,
        kind: NumberKind,
        contains: Optional[str] = None,
        limit: int = 10,
    ) -> List[AvailableNumber]:
        resource = _KIND_RESOURCE[kind]
        url = f"{self._base}/AvailablePhoneNumbers/{country}/{resource}.json"
        params: Dict[str, str] = {"VoiceEnabled": "true", "PageSize": str(limit)}
        if contains:
            params["Contains"] = contains
        async with self._session_factory() as session:
            async with session.get(url, params=params, auth=self._auth()) as response:
                body = await _json_or_text(response)
                if response.status == 404:
                    # Twilio answers 404 when it has no numbers of this type
                    # for the country.
                    return []
                if response.status != 200:
                    logger.warning(
                        f"Platform Twilio number search failed: {response.status} "
                        f"{_twilio_message(body)}"
                    )
                    raise PlatformNumberProviderError(
                        "We couldn't look up numbers just now. Please try again.",
                        detail=_twilio_message(body),
                        status=response.status,
                    )
        numbers = []
        for item in (body or {}).get("available_phone_numbers") or []:
            phone_number = item.get("phone_number")
            if not phone_number:
                continue
            capabilities = item.get("capabilities") or {}
            if capabilities and capabilities.get("voice") is False:
                continue
            numbers.append(
                AvailableNumber(
                    phone_number=phone_number,
                    friendly_name=item.get("friendly_name") or phone_number,
                    kind=kind,
                    locality=item.get("locality") or None,
                    region=item.get("region") or None,
                    address_requirements=item.get("address_requirements") or None,
                )
            )
        return numbers

    async def buy(
        self, phone_number: str, *, voice_url: str, friendly_name: str
    ) -> PurchasedNumber:
        data = {
            "PhoneNumber": phone_number,
            "VoiceUrl": voice_url,
            "VoiceMethod": "POST",
            "FriendlyName": friendly_name[:64],
        }
        if self._bundle_sid:
            data["BundleSid"] = self._bundle_sid
        if self._address_sid:
            data["AddressSid"] = self._address_sid
        async with self._session_factory() as session:
            async with session.post(
                f"{self._base}/IncomingPhoneNumbers.json", data=data, auth=self._auth()
            ) as response:
                body = await _json_or_text(response)
                if response.status not in (200, 201):
                    logger.warning(
                        f"Platform Twilio purchase of {phone_number} failed: "
                        f"{response.status} {_twilio_message(body)}"
                    )
                    raise PlatformNumberProviderError(
                        "We couldn't get that number. It may have just been taken; "
                        "please pick another.",
                        detail=_twilio_message(body),
                        status=response.status,
                    )
        sid = (body or {}).get("sid") if isinstance(body, dict) else None
        if not sid:
            raise PlatformNumberProviderError(
                "We couldn't confirm the new number. Please contact us.",
                detail="Twilio purchase response had no sid",
            )
        bought = (body or {}).get("phone_number") or phone_number
        logger.info(f"Platform Twilio number bought: {bought} (sid={sid})")
        return PurchasedNumber(phone_number=bought, provider_number_id=sid)

    async def release(self, provider_number_id: str) -> None:
        async with self._session_factory() as session:
            async with session.delete(
                f"{self._base}/IncomingPhoneNumbers/{provider_number_id}.json",
                auth=self._auth(),
            ) as response:
                if response.status not in (200, 204, 404):
                    body = await _json_or_text(response)
                    raise PlatformNumberProviderError(
                        "We couldn't release the number.",
                        detail=_twilio_message(body),
                        status=response.status,
                    )
        logger.info(f"Platform Twilio number released (sid={provider_number_id})")

    def configuration_credentials(self) -> Dict[str, Any]:
        return {"account_sid": self.account_id, MANAGED_BY_KEY: MANAGED_BY_LIGHTMOVE}

    def runtime_credentials(self) -> Dict[str, Any]:
        return {"account_sid": self.account_id, "auth_token": self._auth_token}


async def _json_or_text(response) -> Any:
    try:
        return await response.json(content_type=None)
    except Exception:
        try:
            return await response.text()
        except Exception:
            return ""
