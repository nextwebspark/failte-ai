"""Set up logging before importing anything else"""

import asyncio

import sentry_sdk

from api.constants import (
    CORS_ALLOWED_ORIGINS,
    DEPLOYMENT_MODE,
    ENABLE_TELEMETRY,
    SENTRY_DSN,
)
from api.logging_config import ENVIRONMENT, setup_logging

# Set up logging and get the listener for cleanup
setup_logging()


if SENTRY_DSN and (
    DEPLOYMENT_MODE != "oss" or (DEPLOYMENT_MODE == "oss" and ENABLE_TELEMETRY)
):
    from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        send_default_pii=False,
        # The OAuth browser nonce travels in a request body (integrations
        # activate); keep it out of error reports.
        event_scrubber=EventScrubber(denylist=DEFAULT_DENYLIST + ["browser_nonce"]),
        environment=ENVIRONMENT,
    )
    print(f"Sentry initialized in environment: {ENVIRONMENT}")


from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from api.constants import BRAND_APP_URL, BRAND_NAME, PUBLIC_BASE_URL, REDIS_URL
from api.errors.domain import DomainError
from api.errors.mps import (
    MPS_NOT_CONFIGURED_PUBLIC_MESSAGE,
    MPS_UNAVAILABLE_PUBLIC_MESSAGE,
    MPSNotConfiguredError,
    MPSUnavailableError,
)
from api.mcp_server import mcp
from api.routes.main import router as main_router
from api.services.credential_encryption import verify_credential_encryption
from api.services.pipecat.tracing_config import (
    handle_langfuse_sync,
    load_all_org_langfuse_credentials,
)
from api.services.pipecat.tts_cache.runtime import close_speech_cache
from api.services.skills import sync_seed_library_on_startup
from api.services.storage import secure_legacy_minio_bucket
from api.services.tool_integrations.client import close_shared_http_client
from api.services.worker_sync.manager import (
    WorkerSyncManager,
    set_worker_sync_manager,
)
from api.services.worker_sync.protocol import WorkerSyncEventType
from api.tasks.arq import get_arq_redis
from api.utils.cors import resolve_cors_settings

API_PREFIX = "/api/v1"

mcp_app = mcp.http_app(path="/", stateless_http=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fallcha: refuse to start with unreadable or (outside OSS) plaintext
    # credential storage. See api/services/credential_encryption.py.
    await verify_credential_encryption()
    # Fallcha: sync seed skills (api/skills_library) into the library.
    await sync_seed_library_on_startup()
    # Close the old public MinIO bucket even when S3/GCS is the primary backend.
    await asyncio.to_thread(secure_legacy_minio_bucket)

    async with mcp_app.lifespan(app):
        # warmup arq pool
        await get_arq_redis()

        # Pre-register all org-specific Langfuse exporters so they're ready
        # before any pipeline runs, without per-call DB lookups.
        await load_all_org_langfuse_credentials()

        # Start cross-worker sync manager so config changes propagate to all workers
        sync_manager = WorkerSyncManager(REDIS_URL)
        sync_manager.register(
            WorkerSyncEventType.LANGFUSE_CREDENTIALS, handle_langfuse_sync
        )
        await sync_manager.start()
        set_worker_sync_manager(sync_manager)

        from api.services.observability import loop_exceptions, loop_lag, metrics
        from api.services.observability.call_events import (
            delivery as call_event_delivery,
        )

        call_event_delivery.start()

        # Event-loop lag gauge — per-pod saturation signal read off
        # /health/active-calls during autoscaling load tests.
        metrics.start()
        loop_lag.start()
        # Routes exceptions that escape tasks and timer callbacks; demotes one
        # known aioice teardown race and leaves everything else at ERROR.
        loop_exceptions.install()

        try:
            yield  # Run app
        finally:
            logger.info("Starting graceful shutdown...")
            await call_event_delivery.shutdown()
            try:
                await sync_manager.stop()
            finally:
                try:
                    await close_speech_cache()
                finally:
                    await loop_lag.stop()
                    metrics.stop()
                    await close_shared_http_client()


app = FastAPI(
    title=f"{BRAND_NAME} API",
    description=f"API for the {BRAND_NAME} app",
    version="1.0.0",
    openapi_url=f"{API_PREFIX}/openapi.json",
    lifespan=lifespan,
    servers=[
        {"url": BRAND_APP_URL, "description": "Production"},
        {"url": "http://localhost:8000", "description": "Local development"},
    ],
)


@app.exception_handler(MPSNotConfiguredError)
async def handle_mps_not_configured_error(
    _request: Request,
    _exc: MPSNotConfiguredError,
) -> JSONResponse:
    """An MPS-only feature was used on a server without an MPS configured."""

    return JSONResponse(
        status_code=404,
        content={"detail": MPS_NOT_CONFIGURED_PUBLIC_MESSAGE},
    )


@app.exception_handler(MPSUnavailableError)
async def handle_mps_unavailable_error(
    _request: Request,
    _exc: MPSUnavailableError,
) -> JSONResponse:
    """Tell callers this is a LightMove.ai outage, not invalid customer config."""

    return JSONResponse(
        status_code=503,
        content={"detail": MPS_UNAVAILABLE_PUBLIC_MESSAGE},
    )


@app.exception_handler(DomainError)
async def handle_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
    """Map business-rule violations raised below the HTTP layer."""

    content: dict[str, str] = {**exc.extra, "detail": exc.message}
    if exc.code:
        content["code"] = exc.code
    return JSONResponse(status_code=exc.status_code, content=content)


# Configure CORS: an explicit allowlist whenever CORS_ALLOWED_ORIGINS is set,
# and always in production (derived from PUBLIC_BASE_URL when the list is
# unset); "*" without credentials only for local OSS development. The embed
# widget's public endpoints handle their own CORS (PublicEmbedCORSMiddleware
# below). See api/utils/cors.py.
_cors = resolve_cors_settings(
    deployment_mode=DEPLOYMENT_MODE,
    environment=ENVIRONMENT,
    allowed_origins=CORS_ALLOWED_ORIGINS,
    public_base_url=PUBLIC_BASE_URL,
)
cors_origins: list[str] = _cors.allow_origins
cors_allow_credentials = _cors.allow_credentials

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _add_public_embed_cors_middleware() -> None:
    from api.routes.public_embed import PublicEmbedCORSMiddleware

    app.add_middleware(PublicEmbedCORSMiddleware, api_prefix=API_PREFIX)


_add_public_embed_cors_middleware()

api_router = APIRouter()

# include subrouters here
api_router.include_router(main_router)

# main router with api prefix
app.include_router(api_router, prefix=API_PREFIX)

# Mount the MCP server — agents reach it at /api/v1/mcp over Streamable HTTP,
# authenticating with the same X-API-Key header used by the REST API.
# Mounted under /api/v1 so existing reverse-proxy rules (nginx etc.) route it
# without any extra configuration.
app.mount(f"{API_PREFIX}/mcp", mcp_app)
