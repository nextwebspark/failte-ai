"""Startup verification of credential encryption (API and ARQ worker)."""

from __future__ import annotations

from api.constants import DEPLOYMENT_MODE
from api.db import db_client
from api.db.credential_encryption_client import CredentialEncryptionClient
from api.utils.credential_crypto import (
    check_credential_encryption,
    get_credential_cipher,
)


async def verify_credential_encryption() -> None:
    """Raise ``CredentialEncryptionStartupError`` when the process must not
    start: encrypted rows without keys, no keys outside OSS mode, or keys
    that cannot open an existing envelope. See ``check_credential_encryption``.
    """
    sample = await CredentialEncryptionClient(db_client.engine).sample_envelope()
    check_credential_encryption(
        cipher=get_credential_cipher(),
        deployment_mode=DEPLOYMENT_MODE,
        sample_envelope=sample,
    )
