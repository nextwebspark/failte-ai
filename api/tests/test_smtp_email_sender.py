"""SMTP failures say whether another attempt soon is worth making."""

import smtplib
import ssl
from typing import Any
from unittest.mock import patch

import pytest

from api.services.email.base import EmailDeliveryError, EmailFailure, EmailMessage
from api.services.email.settings import SmtpSecurity, SmtpSettings
from api.services.email.smtp_sender import SmtpEmailSender

_MESSAGE = EmailMessage(to="o@example.com", subject="Hi", text="-", html="-")


def _sender() -> SmtpEmailSender:
    settings = SmtpSettings(
        host="smtp.example.com",
        port=587,
        username=None,
        password=None,
        security=SmtpSecurity.NONE,
        timeout_seconds=1,
    )
    return SmtpEmailSender(settings, "LightMove.ai <no-reply@example.com>")


@pytest.mark.parametrize(
    ("error", "failure"),
    [
        (smtplib.SMTPAuthenticationError(535, b"bad credentials"), EmailFailure.FINAL),
        (smtplib.SMTPRecipientsRefused({}), EmailFailure.FINAL),
        (smtplib.SMTPSenderRefused(553, b"no", "x"), EmailFailure.FINAL),
        (
            smtplib.SMTPResponseException(550, b"mailbox unavailable"),
            EmailFailure.FINAL,
        ),
        (smtplib.SMTPNotSupportedError("no STARTTLS"), EmailFailure.FINAL),
        (ssl.SSLCertVerificationError("bad certificate"), EmailFailure.FINAL),
        (ValueError("bad header"), EmailFailure.FINAL),
        (TimeoutError(), EmailFailure.FINAL),
        (smtplib.SMTPResponseException(451, b"try later"), EmailFailure.TRANSIENT),
        (smtplib.SMTPServerDisconnected(), EmailFailure.TRANSIENT),
        (ConnectionResetError(), EmailFailure.TRANSIENT),
    ],
)
async def test_failures_are_classified(error: Exception, failure: EmailFailure) -> None:
    def deliver(_self: Any, _mime: Any) -> None:
        raise error

    with (
        patch.object(SmtpEmailSender, "_deliver", deliver),
        pytest.raises(EmailDeliveryError) as excinfo,
    ):
        await _sender().send(_MESSAGE)

    assert excinfo.value.failure is failure
