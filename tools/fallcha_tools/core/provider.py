"""The provider contract and registry.

A provider is one third-party integration (Google Calendar, Sheets, ...). It
declares metadata for the catalog and registers its MCP tools on a FastMCP
server that the app mounts at ``/mcp/{provider.id}``. Tool functions obtain
the caller's credentials by awaiting the ``ctx_factory`` they were given,
which resolves a :class:`ConnectionContext` from the request's connection key.

Providers may also declare a Pydantic ``config_model`` for per-connection,
non-secret settings, an optional REST router (mounted at
``/v1/{provider.id}``) for plain-HTTP callers, and an :class:`OAuthSpec` if
workspaces can connect them with OAuth2 (bring-your-own client).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

import httpx
from fastapi import APIRouter
from fastmcp import FastMCP
from pydantic import BaseModel, JsonValue

from fallcha_tools.core.db import Database
from fallcha_tools.core.errors import NotFoundError
from fallcha_tools.core.models import AuthMode

PROVIDER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass(frozen=True, slots=True)
class OAuthSpec:
    """How a provider is connected with OAuth2 (authorization code + PKCE).

    ``scopes`` are always requested and must all be granted; workspaces may
    opt into ``optional_scopes`` when they start the flow. ``identity_scopes``
    are requested too, only to read the account's email for the label.
    ``default_config`` seeds a new OAuth connection's config (it is validated
    by the provider's config model like any other config).
    """

    display_name: str
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...]
    optional_scopes: tuple[str, ...] = ()
    identity_scopes: tuple[str, ...] = ()
    userinfo_url: str | None = None
    authorize_params: Mapping[str, str] = field(default_factory=dict)
    default_config: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AccessToken:
    """A provider access token. ``token`` is secret; it is never logged."""

    token: str = field(repr=False)
    expires_at: datetime


class OAuthAccess(Protocol):
    """Fresh access tokens for one OAuth2 connection.

    Implementations refresh lazily (shortly before expiry) and single-flight
    across processes. Raise ``OAuthReconnectRequired`` when the grant is
    revoked, and ``OAuthRefreshFailed`` for transient failures.
    """

    async def access_token(self, *, rejected: str | None = None) -> AccessToken:
        """A token valid for a few more minutes. ``rejected`` is a token the
        provider just refused: it is never returned again (a refresh is
        forced unless another caller has already replaced it)."""
        ...


@dataclass(frozen=True, slots=True)
class ConnectionContext:
    """Everything a tool call needs to act for one workspace connection."""

    org_id: int
    connection_id: uuid.UUID
    provider: str
    auth_mode: AuthMode
    secret: Mapping[str, JsonValue]
    access_token: str | None
    http: httpx.AsyncClient
    config: Mapping[str, JsonValue] = field(default_factory=dict)
    account_label: str | None = None
    scopes_granted: tuple[str, ...] = ()
    # Set for OAuth2 connections only.
    oauth: OAuthAccess | None = None
    # The service's database, for providers that keep per-connection data
    # (every query must filter on ``org_id`` and ``connection_id``).
    db: Database | None = None


ConnectionContextFactory = Callable[[], Awaitable[ConnectionContext]]
# A FastAPI dependency that authenticates a connection key (``Authorization:
# Bearer`` or ``X-API-Key``) for one provider and yields its context.
RestContextDependency = Callable[..., Awaitable[ConnectionContext]]


@dataclass(frozen=True, slots=True)
class ConnectionTestResult:
    ok: bool
    message: str = ""
    account_label: str | None = None


@runtime_checkable
class Provider(Protocol):
    """One integration. Implementations are plain classes with these members."""

    @property
    def id(self) -> str: ...
    @property
    def title(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def icon(self) -> str: ...
    @property
    def auth_family(self) -> str | None:
        """Providers of one family (e.g. "google") share OAuth clients and
        can reuse each other's service-account keys. None: its own family."""
        ...

    @property
    def share_hint(self) -> str | None:
        """What a service account must be given access to, as a phrase
        ("the spreadsheet"), for the connect screen. None if not relevant."""
        ...

    @property
    def auth_modes(self) -> frozenset[AuthMode]: ...
    @property
    def scopes(self) -> tuple[str, ...]: ...
    @property
    def config_model(self) -> type[BaseModel] | None:
        """Model for per-connection config, or None if the provider takes none."""
        ...

    @property
    def oauth(self) -> OAuthSpec | None:
        """OAuth2 details; required iff ``auth_modes`` includes ``oauth2``."""
        ...

    def validate_secret(
        self, auth_mode: AuthMode, secret: Mapping[str, JsonValue]
    ) -> None:
        """Raise :class:`InvalidRequestError` if ``secret`` is unusable.

        Messages must never quote the secret.
        """
        ...

    def register_tools(
        self, mcp: FastMCP[Any], ctx_factory: ConnectionContextFactory
    ) -> None:
        """Register this provider's tools on ``mcp``."""
        ...

    async def test_connection(self, ctx: ConnectionContext) -> ConnectionTestResult:
        """Make a cheap authenticated call to prove the credentials work."""
        ...

    def rest_router(self, ctx_dependency: RestContextDependency) -> APIRouter | None:
        """Optional plain-HTTP routes, mounted at ``/v1/{id}``."""
        ...


class SyncProgress(Protocol):
    """Lets a running sync report that it is alive."""

    async def heartbeat(self, items: int) -> None: ...


@dataclass(frozen=True, slots=True)
class SyncResult:
    """A finished sync: how many items the connection now holds, plus an
    optional note for the admin (e.g. "stopped at max_products")."""

    item_count: int
    note: str | None = None


class SyncFailed(Exception):
    """The sync could not finish. The message is shown to the admin, so it
    must be safe (no secrets, no raw upstream bodies)."""


@runtime_checkable
class SyncableProvider(Protocol):
    """Optional capability: the provider imports data in the background
    (``POST /internal/connections/{id}/sync``). Listed in the catalog as the
    ``sync`` capability."""

    @property
    def sync_item_label(self) -> str:
        """Plural noun for what a sync imports, e.g. "products"."""
        ...

    async def run_sync(
        self, ctx: ConnectionContext, progress: SyncProgress
    ) -> SyncResult:
        """Import the connection's data. Raise :class:`SyncFailed` with an
        admin-safe message on failure."""
        ...


def provider_capabilities(provider: Provider) -> list[str]:
    return ["sync"] if isinstance(provider, SyncableProvider) else []


def credential_family(provider: Provider) -> str:
    """The key OAuth clients are stored under: the family, else the id."""
    return provider.auth_family or provider.id


class ProviderNotFoundError(NotFoundError):
    pass


class ProviderRegistry:
    """Ordered, id-unique collection of providers."""

    def __init__(self, providers: Iterable[Provider] = ()) -> None:
        self._providers: dict[str, Provider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: Provider) -> None:
        if not PROVIDER_ID_PATTERN.fullmatch(provider.id):
            raise ValueError(f"invalid provider id {provider.id!r}")
        if provider.id in self._providers:
            raise ValueError(f"provider {provider.id!r} is already registered")
        if not provider.auth_modes:
            raise ValueError(f"provider {provider.id!r} declares no auth modes")
        if (AuthMode.OAUTH2 in provider.auth_modes) != (provider.oauth is not None):
            raise ValueError(
                f"provider {provider.id!r} must declare an OAuth spec iff it "
                "supports oauth2"
            )
        self._providers[provider.id] = provider

    def get(self, provider_id: str) -> Provider:
        try:
            return self._providers[provider_id]
        except KeyError:
            raise ProviderNotFoundError(f"unknown provider {provider_id!r}") from None

    def __iter__(self) -> Iterator[Provider]:
        return iter(self._providers.values())

    def __len__(self) -> int:
        return len(self._providers)
