from functools import lru_cache

from api.services.email.base import EmailSender
from api.services.email.logging_sender import LoggingEmailSender
from api.services.email.resend_sender import ResendEmailSender
from api.services.email.settings import (
    EmailProvider,
    EmailSettings,
    load_email_settings,
)
from api.services.email.smtp_sender import SmtpEmailSender


def build_email_sender(settings: EmailSettings) -> EmailSender:
    match settings.provider:
        case EmailProvider.SMTP:
            assert settings.smtp is not None
            return SmtpEmailSender(settings.smtp, settings.from_address)
        case EmailProvider.RESEND:
            assert settings.resend_api_key is not None
            return ResendEmailSender(settings.resend_api_key, settings.from_address)
        case EmailProvider.NONE:
            return LoggingEmailSender()


@lru_cache(maxsize=1)
def get_email_sender() -> EmailSender:
    """Process-wide sender chosen from the environment (FastAPI dependency)."""
    return build_email_sender(load_email_settings())
