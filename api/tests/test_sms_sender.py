"""The SMS provider switch and the Twilio sender, against a fake transport
(nothing reaches Twilio)."""

import base64
from urllib.parse import parse_qs

import httpx
import pytest

from api.services.sms.base import SmsDeliveryError, SmsMessage
from api.services.sms.factory import build_sms_sender
from api.services.sms.logging_sender import LoggingSmsSender
from api.services.sms.settings import (
    SmsConfigurationError,
    SmsProvider,
    load_sms_settings,
)
from api.services.sms.twilio_sender import TwilioSmsSender

TWILIO_ENV = {
    "SMS_PROVIDER": "twilio",
    "TWILIO_SMS_ACCOUNT_SID": "AC123",
    "TWILIO_SMS_AUTH_TOKEN": "secret-token",
    "SMS_FROM": "+35315550100",
}


def test_unset_means_log_only():
    settings = load_sms_settings({})
    assert settings.provider is SmsProvider.NONE
    sender = build_sms_sender(settings)
    assert isinstance(sender, LoggingSmsSender)
    assert sender.delivers is False


def test_twilio_settings():
    settings = load_sms_settings(TWILIO_ENV)
    assert settings.provider is SmsProvider.TWILIO
    assert settings.twilio.account_sid == "AC123"
    assert settings.twilio.auth_token.get_secret_value() == "secret-token"
    assert "secret-token" not in repr(settings)
    assert isinstance(build_sms_sender(settings), TwilioSmsSender)


@pytest.mark.parametrize(
    "missing", ["TWILIO_SMS_ACCOUNT_SID", "TWILIO_SMS_AUTH_TOKEN", "SMS_FROM"]
)
def test_twilio_needs_every_setting(missing):
    env = {**TWILIO_ENV, missing: ""}
    with pytest.raises(SmsConfigurationError, match=missing):
        load_sms_settings(env)


@pytest.mark.parametrize("sender", ["LightMove", "Luigis 24", "+353871234567"])
def test_sender_ids_and_numbers_are_accepted(sender):
    assert load_sms_settings({**TWILIO_ENV, "SMS_FROM": sender}).twilio.from_ == sender


@pytest.mark.parametrize("sender", ["0871234567", "TwelveLetters", "Luigi's", "+0123"])
def test_bad_senders_are_rejected(sender):
    with pytest.raises(SmsConfigurationError):
        load_sms_settings({**TWILIO_ENV, "SMS_FROM": sender})


def test_an_unknown_provider_is_rejected():
    with pytest.raises(SmsConfigurationError):
        load_sms_settings({"SMS_PROVIDER": "carrier-pigeon"})


def _sender(handler) -> TwilioSmsSender:
    settings = load_sms_settings(TWILIO_ENV).twilio
    return TwilioSmsSender(settings, transport=httpx.MockTransport(handler))


async def test_twilio_posts_the_message_form():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["form"] = parse_qs(request.content.decode())
        return httpx.Response(201, json={"sid": "SM1", "status": "queued"})

    await _sender(handler).send(SmsMessage(to="+353871234567", body="Hi there"))

    assert (
        seen["url"] == "https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json"
    )
    expected = base64.b64encode(b"AC123:secret-token").decode()
    assert seen["auth"] == f"Basic {expected}"
    assert seen["form"] == {
        "To": ["+353871234567"],
        "From": ["+35315550100"],
        "Body": ["Hi there"],
    }


async def test_a_rejection_raises_with_twilios_reason():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"code": 21211, "message": "The 'To' number is not valid."}
        )

    with pytest.raises(SmsDeliveryError, match="HTTP 400.*not valid"):
        await _sender(handler).send(SmsMessage(to="+353871234567", body="Hi"))


async def test_a_network_error_raises_without_the_token():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(SmsDeliveryError) as exc:
        await _sender(handler).send(SmsMessage(to="+353871234567", body="Hi"))
    assert "secret-token" not in str(exc.value)


async def test_the_log_only_sender_does_not_log_the_whole_number(capsys):
    from loguru import logger

    handler_id = logger.add(lambda m: print(m, end=""), level="INFO")
    try:
        await LoggingSmsSender().send(SmsMessage(to="+353871234567", body="Hi"))
    finally:
        logger.remove(handler_id)
    out = capsys.readouterr().out
    assert "...567" in out
    assert "+353871234567" not in out
