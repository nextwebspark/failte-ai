from loguru import logger

from api.services.sms.base import SmsMessage


class LoggingSmsSender:
    """Default until a provider is configured: logs instead of sending.

    Only the last digits of the number are logged; the body is kept so a
    developer can see what would have gone out.
    """

    @property
    def delivers(self) -> bool:
        return False

    async def send(self, message: SmsMessage) -> None:
        logger.info(
            "SMS_PROVIDER=none; text not sent.\nTo: ...{}\n\n{}",
            message.to[-3:],
            message.body,
        )
