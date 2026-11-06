"""Callers never hear configuration details when their call can't go through."""

import pytest

from api.errors.telephony_errors import (
    CALLER_LINES_BUSY,
    CALLER_UNAVAILABLE,
    TELEPHONY_ERROR_MESSAGES,
    TelephonyError,
    caller_message,
)

TECHNICAL_WORDS = ("workflow", "webhook", "dashboard", "configur", "signature", "SID")


@pytest.mark.parametrize(
    "error", [e for e in TelephonyError if e != TelephonyError.VALID]
)
def test_every_error_has_a_plain_caller_line(error):
    line = caller_message(error)
    assert line.endswith("Goodbye.")
    assert not any(word.lower() in line.lower() for word in TECHNICAL_WORDS), line


def test_busy_lines_and_closed_numbers_say_so():
    assert caller_message(TelephonyError.CONCURRENT_CALL_LIMIT) == CALLER_LINES_BUSY
    assert caller_message(TelephonyError.WORKFLOW_NOT_FOUND) == CALLER_UNAVAILABLE
    assert caller_message(TelephonyError.QUOTA_EXCEEDED) == CALLER_UNAVAILABLE
    assert (
        caller_message(TelephonyError.ORGANIZATION_UNAVAILABLE)
        == (TELEPHONY_ERROR_MESSAGES[TelephonyError.ORGANIZATION_UNAVAILABLE])
    )
    assert caller_message("something unexpected") == CALLER_UNAVAILABLE


@pytest.mark.parametrize(
    "provider", ["twilio", "cloudonix", "exotel", "plivo", "vobiz"]
)
def test_spoken_responses_use_the_caller_line(provider):
    import importlib

    module = importlib.import_module(
        f"api.services.telephony.providers.{provider}.provider"
    )
    cls = next(
        getattr(module, name)
        for name in dir(module)
        if name.endswith("Provider")
        and hasattr(getattr(module, name), "generate_validation_error_response")
    )
    response = cls.generate_validation_error_response(TelephonyError.WORKFLOW_NOT_FOUND)
    body = response.body.decode()
    assert CALLER_UNAVAILABLE in body
    assert "Workflow not found" not in body
