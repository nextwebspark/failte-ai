"""Service configuration, read from environment variables."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @property
    def encryption_keys(self) -> list[str]:
        """Fernet keys, primary (used for new ciphertext) first."""
        return _split_keys(self.encryption_keys_raw.get_secret_value())


def _split_keys(raw: str) -> list[str]:
    return [key.strip() for key in raw.split(",") if key.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # populated from the environment
