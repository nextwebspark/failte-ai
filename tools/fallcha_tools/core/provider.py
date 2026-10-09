"""The provider contract and registry.

A provider is one third-party integration (Google Calendar, Sheets, ...). It
declares metadata for the catalog and registers its MCP tools on a FastMCP
server that the app mounts at ``/mcp/{provider.id}``. Tool functions obtain
the caller's credentials by awaiting the ``ctx_factory`` they were given,
which resolves a :class:`ConnectionContext` from the request's connection key.

Providers may also declare a Pydantic ``config_model`` for per-connection,
non-secret settings, and an optional REST router (mounted at
``/v1/{provider.id}``) for plain-HTTP callers.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx
from fastapi import APIRouter
from fastmcp import FastMCP
from pydantic import BaseModel, JsonValue

from fallcha_tools.core.errors import NotFoundError
from fallcha_tools.core.models import AuthMode

PROVIDER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


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
    def auth_modes(self) -> frozenset[AuthMode]: ...
    @property
    def scopes(self) -> tuple[str, ...]: ...
    @property
    def config_model(self) -> type[BaseModel] | None:
        """Model for per-connection config, or None if the provider takes none."""
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
