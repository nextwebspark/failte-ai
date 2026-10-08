from loguru import logger

from api.services.email.base import EmailMessage


class LoggingEmailSender:
    """Development fallback when no provider is configured.

    Logs the plain-text body, which contains single-use links; never select
    this provider in production.
    """

    @property
    def delivers(self) -> bool:
        return False

    async def send(self, message: EmailMessage) -> None:
        logger.warning(
            "EMAIL_PROVIDER=none; email not sent.\nTo: {}\nSubject: {}\n\n{}",
            message.to,
            message.subject,
            message.text,
        )
