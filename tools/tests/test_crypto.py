from __future__ import annotations

import pytest
from pydantic import JsonValue

from fallcha_tools.core.crypto import DecryptionError, SecretBox, generate_key


def test_string_and_json_round_trip() -> None:
    box = SecretBox([generate_key()])
    token = box.encrypt("s3cret")
    assert token != "s3cret"
    assert box.decrypt(token) == "s3cret"

    payload: JsonValue = {
        "type": "service_account",
        "nested": {"n": 1},
        "list": [1, "a"],
    }
    assert box.decrypt_json(box.encrypt_json(payload)) == payload


def test_rotation_old_key_decrypts_and_new_key_encrypts() -> None:
    old_key, new_key = generate_key(), generate_key()
    old_box = SecretBox([old_key])
    legacy = old_box.encrypt("value")

    rotating = SecretBox([new_key, old_key])
    assert rotating.decrypt(legacy) == "value"

    rotated = rotating.rotate(legacy)
    assert SecretBox([new_key]).decrypt(rotated) == "value"
    with pytest.raises(DecryptionError):
        old_box.decrypt(rotated)

    fresh = rotating.encrypt("other")
    assert SecretBox([new_key]).decrypt(fresh) == "other"
    with pytest.raises(DecryptionError):
        old_box.decrypt(fresh)


def test_unknown_key_and_garbage_raise_decryption_error() -> None:
    token = SecretBox([generate_key()]).encrypt("x")
    with pytest.raises(DecryptionError):
        SecretBox([generate_key()]).decrypt(token)
    with pytest.raises(DecryptionError):
        SecretBox([generate_key()]).rotate("not-a-token")


def test_invalid_key_rejected() -> None:
    with pytest.raises(ValueError):
        SecretBox(["not-a-fernet-key"])
    with pytest.raises(ValueError):
        SecretBox([])
