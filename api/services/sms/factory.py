from functools import lru_cache

from api.services.sms.base import SmsSender
from api.services.sms.logging_sender import LoggingSmsSender
from api.services.sms.settings import SmsProvider, SmsSettings, load_sms_settings
from api.services.sms.twilio_sender import TwilioSmsSender


def build_sms_sender(settings: SmsSettings) -> SmsSender:
    match settings.provider:
        case SmsProvider.TWILIO:
            assert settings.twilio is not None
            return TwilioSmsSender(settings.twilio)
        case SmsProvider.NONE:
            return LoggingSmsSender()


@lru_cache(maxsize=1)
def get_sms_sender() -> SmsSender:
    """Process-wide sender chosen from the environment."""
    return build_sms_sender(load_sms_settings())
