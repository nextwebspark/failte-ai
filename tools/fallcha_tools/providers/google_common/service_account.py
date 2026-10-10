"""The Google service-account key format (stored encrypted in
``connections.secret_enc``), shared by every Google provider."""

from __future__ import annotations

from typing import Literal

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ServiceAccountKey(BaseModel):
    """The fields used from a Google service-account JSON key.

    ``token_uri`` is deliberately ignored: tokens are always minted at Google's
    fixed endpoint, so a crafted key cannot redirect the signed assertion.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    type: Literal["service_account"]
    client_email: str = Field(
        min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$"
    )
    private_key: str = Field(min_length=1, repr=False)
    private_key_id: str | None = Field(default=None, max_length=128)

    @field_validator("private_key")
    @classmethod
    def _rsa_pem(cls, value: str) -> str:
        try:
            key = load_pem_private_key(value.encode(), password=None)
        except (ValueError, TypeError):
            raise ValueError("private_key is not a PEM private key") from None
        if not isinstance(key, RSAPrivateKey):
            raise ValueError("private_key must be an RSA key")
        return value

    def signer(self) -> RSAPrivateKey:
        key = load_pem_private_key(self.private_key.encode(), password=None)
        assert isinstance(key, RSAPrivateKey)  # checked by the validator
        return key
