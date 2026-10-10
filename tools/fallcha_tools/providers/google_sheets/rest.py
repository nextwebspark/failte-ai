"""REST compatibility: ``POST /v1/google-sheets/order_lookup``.

Takes the old calendar shim's ``/order_lookup`` body and returns its
response shape, so an existing ``http_api`` tool only needs a new URL and a
Sheets connection key (as Bearer or ``X-API-Key``).
"""

# No ``from __future__ import annotations``: FastAPI must resolve the
# dependency alias defined inside ``build_rest_router`` at runtime.

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from fallcha_tools.core.provider import ConnectionContext, RestContextDependency
from fallcha_tools.providers.google_common.errors import (
    BadArgumentError,
    GoogleToolError,
    NotConfiguredError,
)
from fallcha_tools.providers.google_sheets.schemas import (
    OrderLookupRequest,
    OrderLookupResult,
)
from fallcha_tools.providers.google_sheets.service import ServiceFactory


def _status_for(exc: GoogleToolError) -> int:
    if isinstance(exc, BadArgumentError):
        return status.HTTP_400_BAD_REQUEST
    if isinstance(exc, NotConfiguredError):
        return status.HTTP_409_CONFLICT
    return status.HTTP_502_BAD_GATEWAY


def build_rest_router(
    ctx_dependency: RestContextDependency, service_for: ServiceFactory
) -> APIRouter:
    router = APIRouter(tags=["google-sheets"])
    Ctx = Annotated[ConnectionContext, Depends(ctx_dependency)]

    @router.post("/order_lookup", response_model_exclude_none=True)
    async def order_lookup(body: OrderLookupRequest, ctx: Ctx) -> OrderLookupResult:
        try:
            return await service_for(ctx).look_up_order(
                body.caller_name, body.address_or_eircode, body.order_id
            )
        except GoogleToolError as exc:
            raise HTTPException(_status_for(exc), str(exc)) from None

    return router
