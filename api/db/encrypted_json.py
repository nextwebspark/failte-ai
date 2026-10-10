"""``EncryptedJSON``: a JSON column whose dict values are encrypted at rest.

The stored value stays valid JSON (an envelope, see
``api.utils.credential_crypto``), so the column keeps its ``JSON`` type and
needs no schema migration. Reads accept legacy plaintext dicts. Consequence:
the database cannot filter on the contents — query by other columns and
inspect the decrypted dict in Python.
"""

from __future__ import annotations

from typing import Any

from pydantic import JsonValue
from sqlalchemy.engine import Dialect
from sqlalchemy.types import JSON, TypeDecorator

from api.utils.credential_crypto import (
    CredentialData,
    decrypt_credential_data,
    encrypt_credential_data,
)


class EncryptedJSON(TypeDecorator[CredentialData]):
    impl = JSON
    cache_ok = True

    def process_bind_param(
        self, value: CredentialData | None, dialect: Dialect
    ) -> CredentialData | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise TypeError("EncryptedJSON values must be dicts")
        return encrypt_credential_data(value)

    def process_result_value(
        self, value: Any, dialect: Dialect
    ) -> CredentialData | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise TypeError("EncryptedJSON column held a non-object JSON value")
        stored: dict[str, JsonValue] = value
        return decrypt_credential_data(stored)
