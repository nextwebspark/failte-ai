"""Envelope encryption for secrets at rest (Fernet, with key rotation).

``TOOLS_ENCRYPTION_KEYS`` holds one or more Fernet keys. The first key
encrypts; every key can decrypt, so a new key is rolled out by prepending it,
re-encrypting with :meth:`SecretBox.rotate`, then dropping the old key.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from pydantic import JsonValue


class DecryptionError(Exception):
    """Ciphertext is corrupt or was made with a key that is no longer configured."""


class SecretBox:
    """Encrypts strings and JSON values to URL-safe text tokens."""

    def __init__(self, keys: Sequence[str]) -> None:
        if not keys:
            raise ValueError("at least one encryption key is required")
        try:
            self._fernet = MultiFernet([Fernet(key.encode()) for key in keys])
        except ValueError as exc:
            raise ValueError("invalid Fernet key in TOOLS_ENCRYPTION_KEYS") from exc

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise DecryptionError("unable to decrypt secret") from exc

    def encrypt_json(self, value: JsonValue) -> str:
        return self.encrypt(json.dumps(value, separators=(",", ":"), sort_keys=True))

    def decrypt_json(self, token: str) -> JsonValue:
        decoded: JsonValue = json.loads(self.decrypt(token))
        return decoded

    def rotate(self, token: str) -> str:
        """Re-encrypt ``token`` under the primary key (it may use any known key)."""
        try:
            return self._fernet.rotate(token.encode()).decode()
        except InvalidToken as exc:
            raise DecryptionError("unable to decrypt secret") from exc


def generate_key() -> str:
    """A fresh Fernet key, for operators and tests."""
    return Fernet.generate_key().decode()
