"""Encryption at rest for ``external_credentials.credential_data``.

A credential's secret fields are stored as a versioned envelope inside the
existing JSON column::

    {"_enc": "v1", "ct": "<Fernet token of the JSON-encoded dict>"}

Keys come from ``CREDENTIALS_ENCRYPTION_KEYS`` (comma-separated Fernet keys).
The first key encrypts; every listed key decrypts, so rotation is: prepend a
new key, run ``python -m scripts.reencrypt_credentials``, then drop the old
key. Without keys, values are written as plaintext (backwards compatible with
OSS installs); envelopes found in that mode cannot be read and raise
:class:`CredentialDecryptionError`. :func:`check_credential_encryption` is the
startup policy run by the API and worker (see
``api/services/credential_encryption.py``).

Plaintext legacy rows (any dict that is not an envelope) are always readable,
so enabling encryption needs no downtime: rows are encrypted on their next
write, by the backfill migration, or by the re-encryption script.

Nothing here logs credential contents.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from loguru import logger
from pydantic import JsonValue

from api.constants import CREDENTIALS_ENCRYPTION_KEYS

ENVELOPE_MARKER = "_enc"
ENVELOPE_VERSION = "v1"
_CIPHERTEXT = "ct"

CredentialData = dict[str, JsonValue]


class CredentialDecryptionError(Exception):
    """An envelope is corrupt, has an unknown version, or no configured key
    can open it (e.g. CREDENTIALS_ENCRYPTION_KEYS was removed or rotated
    past the key that wrote it)."""


def is_envelope(value: object) -> bool:
    """True when ``value`` is exactly an encrypted envelope (no other keys)."""
    return (
        isinstance(value, Mapping)
        and set(value.keys()) == {ENVELOPE_MARKER, _CIPHERTEXT}
        and isinstance(value.get(ENVELOPE_MARKER), str)
        and isinstance(value.get(_CIPHERTEXT), str)
    )


class CredentialCipher:
    """Seals credential dicts into envelopes and opens them again."""

    def __init__(self, keys: Sequence[str]) -> None:
        if not keys:
            raise ValueError("at least one encryption key is required")
        try:
            self._fernet = MultiFernet([Fernet(key.encode()) for key in keys])
        except ValueError as exc:
            # Never echo the key material itself.
            raise ValueError(
                "CREDENTIALS_ENCRYPTION_KEYS contains an invalid Fernet key"
            ) from exc

    def seal(self, data: Mapping[str, JsonValue]) -> dict[str, str]:
        plaintext = json.dumps(dict(data), separators=(",", ":"), sort_keys=True)
        token = self._fernet.encrypt(plaintext.encode()).decode()
        return {ENVELOPE_MARKER: ENVELOPE_VERSION, _CIPHERTEXT: token}

    def open(self, envelope: Mapping[str, object]) -> CredentialData:
        token = _token_of(envelope)
        try:
            decoded: object = json.loads(self._fernet.decrypt(token.encode()))
        except InvalidToken as exc:
            raise CredentialDecryptionError(
                "unable to decrypt credential data with the configured keys"
            ) from exc
        if not isinstance(decoded, dict):
            raise CredentialDecryptionError("decrypted credential data is not a dict")
        return decoded

    def rotate(self, envelope: Mapping[str, object]) -> dict[str, str]:
        """Re-encrypt ``envelope`` under the primary key (any known key may
        have written it). Opaque: the plaintext is never materialised here."""
        token = _token_of(envelope)
        try:
            rotated = self._fernet.rotate(token.encode()).decode()
        except InvalidToken as exc:
            raise CredentialDecryptionError(
                "unable to decrypt credential data with the configured keys"
            ) from exc
        return {ENVELOPE_MARKER: ENVELOPE_VERSION, _CIPHERTEXT: rotated}


def _token_of(envelope: Mapping[str, object]) -> str:
    if not is_envelope(envelope):
        raise CredentialDecryptionError("value is not an encrypted envelope")
    if envelope[ENVELOPE_MARKER] != ENVELOPE_VERSION:
        raise CredentialDecryptionError(
            f"unsupported credential envelope version {envelope[ENVELOPE_MARKER]!r}"
        )
    token = envelope[_CIPHERTEXT]
    assert isinstance(token, str)  # guaranteed by is_envelope
    return token


def generate_key() -> str:
    """A fresh Fernet key, for operators and tests."""
    return Fernet.generate_key().decode()


# Built at import so a malformed key fails the process at startup, not on the
# first credential write. Tests swap it by patching ``_cipher``.
_cipher: CredentialCipher | None = (
    CredentialCipher(CREDENTIALS_ENCRYPTION_KEYS)
    if CREDENTIALS_ENCRYPTION_KEYS
    else None
)


def get_credential_cipher() -> CredentialCipher | None:
    """The process cipher, or ``None`` when encryption is not configured."""
    return _cipher


class CredentialEncryptionStartupError(RuntimeError):
    """The process must not start with this encryption configuration."""


def check_credential_encryption(
    *,
    cipher: CredentialCipher | None,
    deployment_mode: str,
    sample_envelope: Mapping[str, object] | None,
) -> None:
    """Startup policy for credential encryption.

    - Encrypted rows exist but no keys are configured: refuse (every mode),
      since those credentials could not be read.
    - No keys outside OSS mode: refuse; OSS keeps plaintext with a warning.
    - Keys configured: one existing envelope (``sample_envelope``) must
      decrypt, catching a wrong or dropped key before any call needs it.
    """
    if cipher is None:
        if sample_envelope is not None:
            raise CredentialEncryptionStartupError(
                "external_credentials holds encrypted rows but "
                "CREDENTIALS_ENCRYPTION_KEYS is not set; configure the keys "
                "that encrypted them."
            )
        if deployment_mode != "oss":
            raise CredentialEncryptionStartupError(
                f"CREDENTIALS_ENCRYPTION_KEYS must be set when DEPLOYMENT_MODE "
                f"is {deployment_mode!r}; workspace credentials would otherwise "
                "be stored in plaintext."
            )
        logger.warning(
            "CREDENTIALS_ENCRYPTION_KEYS is not set: external credential secrets "
            "are stored in plaintext. Set it to one or more Fernet keys to "
            "encrypt them at rest."
        )
        return
    if sample_envelope is not None:
        try:
            cipher.open(sample_envelope)
        except CredentialDecryptionError as exc:
            raise CredentialEncryptionStartupError(
                "CREDENTIALS_ENCRYPTION_KEYS cannot decrypt an existing "
                "credential; a key that encrypted stored rows is missing "
                "(re-add it, run `python -m scripts.reencrypt_credentials`, "
                "then remove it)."
            ) from exc


def encrypt_credential_data(data: Mapping[str, JsonValue]) -> CredentialData:
    """The value to persist: an envelope, or ``data`` itself in plaintext mode.

    An envelope-shaped plaintext dict is always refused: stored in plaintext
    mode it would be indistinguishable from ciphertext on read.
    """
    if is_envelope(data):
        raise ValueError(
            f"credential_data must not be shaped like an encrypted envelope "
            f"({ENVELOPE_MARKER!r} and {_CIPHERTEXT!r} are reserved)"
        )
    cipher = _cipher
    if cipher is None:
        return dict(data)
    return dict(cipher.seal(data))


def decrypt_credential_data(stored: Mapping[str, JsonValue]) -> CredentialData:
    """The plaintext dict for a stored value (legacy plaintext passes through)."""
    if not is_envelope(stored):
        return dict(stored)
    cipher = _cipher
    if cipher is None:
        raise CredentialDecryptionError(
            "credential data is encrypted but CREDENTIALS_ENCRYPTION_KEYS is not set"
        )
    return cipher.open(stored)
