"""Service configuration, read from environment variables."""

from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# An OAuth client id: printable ASCII, no spaces (as for workspace clients).
_CLIENT_ID = re.compile(r"[\x21-\x7e]{1,256}")


def normalize_database_url(url: str) -> str:
    """Force the asyncpg driver so plain ``postgresql://`` URLs work too."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    return url


class DatabaseSettings(BaseSettings):
    """The subset Alembic needs; it must not require the app's secrets."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")

    @field_validator("database_url")
    @classmethod
    def _asyncpg_driver(cls, value: str) -> str:
        return normalize_database_url(value)


class Settings(DatabaseSettings):
    """Full runtime configuration of the tools service."""

    encryption_keys_raw: SecretStr = Field(alias="TOOLS_ENCRYPTION_KEYS")
    internal_secret: SecretStr = Field(alias="TOOLS_INTERNAL_SECRET")
    # Public origin (plus optional path prefix) that serves /oauth/*; OAuth
    # redirect URIs are built from it. Unset disables OAuth.
    public_base_url: str = Field(default="", alias="TOOLS_PUBLIC_BASE_URL")
    # Fixed UI page the OAuth callback redirects the browser back to. Never
    # taken from a request, so the callback cannot be an open redirect.
    ui_return_url: str = Field(default="", alias="TOOLS_UI_RETURN_URL")
    # The platform's own Google OAuth client, offered to every workspace next
    # to the clients they bring. Both or neither; unset offers none.
    google_client_id: str | None = Field(default=None, alias="TOOLS_GOOGLE_CLIENT_ID")
    google_client_secret: SecretStr | None = Field(
        default=None, alias="TOOLS_GOOGLE_CLIENT_SECRET"
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @field_validator("public_base_url", "ui_return_url")
    @classmethod
    def _absolute_http_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("must be an absolute http(s) URL")
        if parts.fragment or parts.username or parts.password:
            raise ValueError("must not contain a fragment or credentials")
        return value.rstrip("/") if not parts.query else value

    @field_validator("internal_secret")
    @classmethod
    def _secret_strength(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 16:
            raise ValueError("TOOLS_INTERNAL_SECRET must be at least 16 characters")
        return value

    @field_validator("encryption_keys_raw")
    @classmethod
    def _keys_present(cls, value: SecretStr) -> SecretStr:
        if not _split_keys(value.get_secret_value()):
            raise ValueError("TOOLS_ENCRYPTION_KEYS must contain at least one key")
        return value

    @field_validator("google_client_id", "google_client_secret", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        # Docker Compose passes unset variables as "".
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("google_client_id")
    @classmethod
    def _client_id_shape(cls, value: str | None) -> str | None:
        if value is not None and not _CLIENT_ID.fullmatch(value):
            raise ValueError("TOOLS_GOOGLE_CLIENT_ID must be printable ASCII")
        return value

    @model_validator(mode="after")
    def _google_client_complete(self) -> Settings:
        if (self.google_client_id is None) != (self.google_client_secret is None):
            raise ValueError(
                "set both TOOLS_GOOGLE_CLIENT_ID and TOOLS_GOOGLE_CLIENT_SECRET, "
                "or neither"
            )
        return self

    @property
    def encryption_keys(self) -> list[str]:
        """Fernet keys, primary (used for new ciphertext) first."""
        return _split_keys(self.encryption_keys_raw.get_secret_value())


def _split_keys(raw: str) -> list[str]:
    return [key.strip() for key in raw.split(",") if key.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # populated from the environment
