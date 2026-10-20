from types import SimpleNamespace

from pipecat.utils.run_context import run_id_var

from api.logging_config import enrich_log_record


def _record(level: int, extra: dict | None = None) -> dict:
    return {
        "level": SimpleNamespace(no=level),
        "extra": dict(extra or {}),
    }


def test_error_without_classification_gets_operator_fallback():
    token = run_id_var.set("2250")
    try:
        record = _record(40)
        enrich_log_record(record)
    finally:
        run_id_var.reset(token)

    assert record["extra"] == {
        "run_id": "2250",
        "error_owner": "operator",
        "error_type": "system_error",
        "error_source": "platform",
        "error_code": "unclassified-error",
        "classified": True,
        "classification_mode": "fallback",
    }


def test_explicit_error_classification_is_preserved():
    record = _record(
        40,
        {
            "error_owner": "user",
            "error_type": "config_error",
            "error_source": "stt",
            "error_code": "deepgram-401",
            "classified": False,
        },
    )

    enrich_log_record(record)

    assert record["extra"]["error_owner"] == "user"
    assert record["extra"]["error_type"] == "config_error"
    assert record["extra"]["error_source"] == "stt"
    assert record["extra"]["error_code"] == "deepgram-401"
    assert record["extra"]["classified"] is True
    assert record["extra"]["classification_mode"] == "explicit"


def test_partial_error_classification_falls_back_as_a_unit():
    record = _record(40, {"error_owner": "user", "error_type": "config_error"})

    enrich_log_record(record)

    assert record["extra"]["error_owner"] == "operator"
    assert record["extra"]["error_type"] == "system_error"
    assert record["extra"]["error_source"] == "platform"
    assert record["extra"]["error_code"] == "unclassified-error"
    assert record["extra"]["classification_mode"] == "fallback"


def test_warning_only_gets_run_context():
    record = _record(30)

    enrich_log_record(record)

    assert record["extra"] == {"run_id": None}


def test_phone_numbers_and_emails_are_redacted():
    from api.logging_config import redact_personal_data

    line = "From +353871234567 to %2B14155550123, user jane.doe@example.ie"
    assert redact_personal_data(line) == (
        "From +*********567 to +********123, user ***@example.ie"
    )


def test_redaction_leaves_ids_and_timestamps_alone():
    from api.logging_config import redact_personal_data

    line = "run 1234567890 at 2026-10-20T10:00:00+01:00 port 9000"
    assert redact_personal_data(line) == line


def test_bare_phone_numbers_are_masked_at_the_call_site():
    from api.logging_config import mask_phone

    assert mask_phone("353871234567") == "*********567"
    assert mask_phone("+14155550123") == "+********123"
    assert mask_phone("12") == "12"
    assert mask_phone(None) is None


def test_webhook_payload_phone_fields_are_masked():
    from api.logging_config import mask_phone_fields

    payload = {
        "From": "353871234567",
        "To": "14155550123",
        "CallUUID": "abc-123",
        "Duration": "42",
        "data": {"payload": {"from": "+353871234567", "call_id": "x"}},
        "legs": [{"CallFrom": "09876543210"}],
    }

    assert mask_phone_fields(payload) == {
        "From": "*********567",
        "To": "********123",
        "CallUUID": "abc-123",
        "Duration": "42",
        "data": {"payload": {"from": "+*********567", "call_id": "x"}},
        "legs": [{"CallFrom": "********210"}],
    }
    assert payload["From"] == "353871234567"  # the original is untouched
