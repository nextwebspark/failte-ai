"""Text message (SMS) configuration, parsed once from the environment."""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from pydantic import SecretStr


class SmsProvider(StrEnum):
    # Log messages instead of sending them (the default).
    NONE = "none"
    TWILIO = "twilio"


@dataclass(frozen=True, slots=True)
class TwilioSmsSettings:
    account_sid: str
    auth_token: SecretStr
    # An E.164 number on the account, or an alphanumeric sender id.
    from_: str
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class SmsSettings:
    provider: SmsProvider
    twilio: TwilioSmsSettings | None


class SmsConfigurationError(ValueError):
    pass


_E164 = re.compile(r"^\+[1-9]\d{7,14}$")
# Alphanumeric sender id: 1-11 letters, digits and spaces, at least one letter.
_ALPHANUMERIC_SENDER = re.compile(r"^(?=.*[A-Za-z])[A-Za-z0-9 ]{1,11}$")


def _valid_sender(value: str) -> bool:
    return bool(_E164.match(value) or _ALPHANUMERIC_SENDER.match(value))


def load_sms_settings(env: Mapping[str, str] = os.environ) -> SmsSettings:
    raw = (env.get("SMS_PROVIDER") or SmsProvider.NONE).strip().lower()
    try:
        provider = SmsProvider(raw)
    except ValueError:
        raise SmsConfigurationError(
            f"SMS_PROVIDER must be one of {', '.join(p.value for p in SmsProvider)}"
        ) from None

    if provider is SmsProvider.NONE:
        return SmsSettings(provider=provider, twilio=None)

    sid = (env.get("TWILIO_SMS_ACCOUNT_SID") or "").strip()
    token = (env.get("TWILIO_SMS_AUTH_TOKEN") or "").strip()
    sender = (env.get("SMS_FROM") or "").strip()
    missing = [
        name
        for name, value in (
            ("TWILIO_SMS_ACCOUNT_SID", sid),
            ("TWILIO_SMS_AUTH_TOKEN", token),
            ("SMS_FROM", sender),
        )
        if not value
    ]
    if missing:
        raise SmsConfigurationError(
            f"{', '.join(missing)} required for SMS_PROVIDER=twilio"
        )
    if not _valid_sender(sender):
        raise SmsConfigurationError(
            "SMS_FROM must be an E.164 number (+353...) or an alphanumeric "
            "sender id of up to 11 letters and digits"
        )
    return SmsSettings(
        provider=provider,
        twilio=TwilioSmsSettings(
            account_sid=sid,
            auth_token=SecretStr(token),
            from_=sender,
            timeout_seconds=float(env.get("SMS_TIMEOUT_SECONDS", "15")),
        ),
    )
