"""Email configuration, parsed once from the environment."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from pydantic import SecretStr


class EmailProvider(StrEnum):
    # Log messages instead of sending them (local development).
    NONE = "none"
    SMTP = "smtp"
    RESEND = "resend"


class SmtpSecurity(StrEnum):
    STARTTLS = "starttls"
    SSL = "ssl"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class SmtpSettings:
    host: str
    port: int
    username: str | None
    password: SecretStr | None
    security: SmtpSecurity
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class EmailSettings:
    provider: EmailProvider
    from_address: str
    smtp: SmtpSettings | None
    resend_api_key: SecretStr | None


class EmailConfigurationError(ValueError):
    pass


def load_email_settings(env: Mapping[str, str] = os.environ) -> EmailSettings:
    provider = EmailProvider(env.get("EMAIL_PROVIDER", EmailProvider.NONE).lower())
    from_address = env.get("EMAIL_FROM", "Dograh <no-reply@localhost>")

    smtp: SmtpSettings | None = None
    resend_api_key: SecretStr | None = None
    if provider is EmailProvider.SMTP:
        host = env.get("SMTP_HOST")
        if not host:
            raise EmailConfigurationError(
                "SMTP_HOST is required for EMAIL_PROVIDER=smtp"
            )
        password = env.get("SMTP_PASSWORD")
        smtp = SmtpSettings(
            host=host,
            port=int(env.get("SMTP_PORT", "587")),
            username=env.get("SMTP_USERNAME") or None,
            password=SecretStr(password) if password else None,
            security=SmtpSecurity(env.get("SMTP_SECURITY", SmtpSecurity.STARTTLS)),
            timeout_seconds=float(env.get("SMTP_TIMEOUT_SECONDS", "15")),
        )
    elif provider is EmailProvider.RESEND:
        key = env.get("RESEND_API_KEY")
        if not key:
            raise EmailConfigurationError(
                "RESEND_API_KEY is required for EMAIL_PROVIDER=resend"
            )
        resend_api_key = SecretStr(key)

    return EmailSettings(
        provider=provider,
        from_address=from_address,
        smtp=smtp,
        resend_api_key=resend_api_key,
    )
