"""Plain-HTTP access to provider tools, at ``/v1/{provider}/...``.

This exists for callers that cannot speak MCP (the voice engine's
``http_api`` tools during migration). The caller presents a connection key
either as ``Authorization: Bearer <key>`` or, for drop-in compatibility with
the old single-tenant shims, as ``X-API-Key: <key>``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Header, HTTPException, status

from fallcha_tools.core.container import ServicesDep
from fallcha_tools.core.errors import ToolsError
from fallcha_tools.core.provider import ConnectionContext, RestContextDependency
from fallcha_tools.core.repositories import KeyRepository

_UNAUTHORIZED = "invalid or missing connection key"


def _presented_key(authorization: str | None, x_api_key: str | None) -> str | None:
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
        return None
    return x_api_key.strip() if x_api_key else None


def connection_key_dependency(provider_id: str) -> RestContextDependency:
    """A dependency resolving the request's key to a context for ``provider_id``."""

    async def dependency(
        services: ServicesDep,
        authorization: Annotated[str | None, Header()] = None,
        x_api_key: Annotated[str | None, Header()] = None,
    ) -> ConnectionContext:
        key = _presented_key(authorization, x_api_key)
        if key is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, _UNAUTHORIZED)
        async with services.db.session() as session:
            principal = await KeyRepository(session).lookup_key(key)
        if principal is None or principal.provider != provider_id:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, _UNAUTHORIZED)
        try:
            return await services.contexts.load(
                principal.org_id, principal.connection_id, provider_id
            )
        except ToolsError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, _UNAUTHORIZED) from None

    return dependency
