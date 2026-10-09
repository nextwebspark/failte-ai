"""Application factory.

Run with ``uvicorn fallcha_tools.app:create_app --factory``.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger

from fallcha_tools.config import Settings, get_settings
from fallcha_tools.core.auth import KeyLookup
from fallcha_tools.core.container import AppServices
from fallcha_tools.core.context import ContextLoader
from fallcha_tools.core.crypto import SecretBox
from fallcha_tools.core.db import Database
from fallcha_tools.core.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    ToolsError,
)
from fallcha_tools.core.mcp import ConnectionResolver, McpGateway, McpMounts
from fallcha_tools.core.provider import ProviderRegistry
from fallcha_tools.core.repositories import KeyPrincipal, KeyRepository
from fallcha_tools.providers import build_registry
from fallcha_tools.routes import internal
from fallcha_tools.routes.rest import connection_key_dependency

_ERROR_STATUS: dict[type[ToolsError], int] = {
    NotFoundError: 404,
    ConflictError: 409,
    InvalidRequestError: 422,
}


def _make_key_lookup(db: Database) -> KeyLookup:
    async def lookup(key: str) -> KeyPrincipal | None:
        async with db.session() as session:
            return await KeyRepository(session).lookup_key(key)

    return lookup


async def _tools_error_handler(_: Request, exc: Exception) -> JSONResponse:
    status_code = next(
        (code for cls, code in _ERROR_STATUS.items() if isinstance(exc, cls)), 400
    )
    return JSONResponse({"detail": str(exc)}, status_code=status_code)


async def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    # FastAPI's default echoes each offending ``input`` (and ``ctx``) back;
    # request bodies here carry secrets, so only location and reason are kept.
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    detail = [
        {
            "loc": list(err.get("loc", ())),
            "msg": err.get("msg"),
            "type": err.get("type"),
        }
        for err in errors
    ]
    return JSONResponse({"detail": detail}, status_code=422)


def create_app(
    settings: Settings | None = None, registry: ProviderRegistry | None = None
) -> FastAPI:
    settings = settings or get_settings()
    registry = registry if registry is not None else build_registry(settings)

    logger.remove()
    # No variable values in tracebacks: they could include decrypted secrets.
    logger.add(
        sys.stderr,
        level=settings.log_level.upper(),
        backtrace=False,
        diagnose=False,
    )

    box = SecretBox(settings.encryption_keys)
    db = Database(settings.database_url)
    http = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0))
    contexts = ContextLoader(db=db, box=box, http=http)
    mounts = McpMounts(registry, ConnectionResolver(contexts), _make_key_lookup(db))
    services = AppServices(
        settings=settings,
        db=db,
        box=box,
        http=http,
        registry=registry,
        mcp=mounts,
        contexts=contexts,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("fallcha-tools starting with providers: {}", list(mounts.apps))
        try:
            async with mounts.lifespan():
                yield
        finally:
            await http.aclose()
            await db.dispose()

    app = FastAPI(title="Fallcha Tools", lifespan=lifespan)
    app.state.services = services
    app.add_exception_handler(ToolsError, _tools_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(internal.router)
    for provider in registry:
        router = provider.rest_router(connection_key_dependency(provider.id))
        if router is not None:
            app.include_router(router, prefix=f"/v1/{provider.id}")
    app.mount("/mcp", McpGateway(mounts.apps))
    return app
