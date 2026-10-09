"""REST compatibility routes mirroring the old calendar shim's HTTP contract.

``POST /v1/google-calendar/{availability,book,order_lookup,cancel}`` take the
shim's JSON bodies and return its response shapes, so existing ``http_api``
tools only need a new URL and a connection key (as Bearer or ``X-API-Key``).
"""

# No ``from __future__ import annotations``: FastAPI must resolve the
# dependency alias defined inside ``build_rest_router`` at runtime.

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from fallcha_tools.core.provider import ConnectionContext, RestContextDependency
from fallcha_tools.providers.google_calendar.errors import (
    BadArgumentError,
    CalendarToolError,
    NotConfiguredError,
)
from fallcha_tools.providers.google_calendar.schemas import (
    AvailabilityRequest,
    AvailabilityResult,
    BookingResult,
    BookRequest,
    CancelRequest,
    CancelResult,
    OrderLookupRequest,
    OrderLookupResult,
)
from fallcha_tools.providers.google_calendar.service import (
    CalendarService,
    ServiceFactory,
)


def _status_for(exc: CalendarToolError) -> int:
    if isinstance(exc, BadArgumentError):
        return status.HTTP_400_BAD_REQUEST
    if isinstance(exc, NotConfiguredError):
        return status.HTTP_409_CONFLICT
    return status.HTTP_502_BAD_GATEWAY


async def _run[T](
    ctx: ConnectionContext,
    service_for: ServiceFactory,
    action: Callable[[CalendarService], Awaitable[T]],
) -> T:
    try:
        return await action(service_for(ctx))
    except CalendarToolError as exc:
        raise HTTPException(_status_for(exc), str(exc)) from None


def build_rest_router(
    ctx_dependency: RestContextDependency, service_for: ServiceFactory
) -> APIRouter:
    router = APIRouter(tags=["google-calendar"])
    Ctx = Annotated[ConnectionContext, Depends(ctx_dependency)]

    @router.post("/availability", response_model_exclude_none=True)
    async def availability(body: AvailabilityRequest, ctx: Ctx) -> AvailabilityResult:
        return await _run(
            ctx,
            service_for,
            lambda svc: svc.availability(body.relative_day, body.part_of_day),
        )

    @router.post("/book", response_model_exclude_none=True)
    async def book(body: BookRequest, ctx: Ctx) -> BookingResult:
        return await _run(
            ctx,
            service_for,
            lambda svc: svc.book(
                body.slot_id, body.caller_name, body.caller_phone, body.reason
            ),
        )

    @router.post("/cancel", response_model_exclude_none=True)
    async def cancel(body: CancelRequest, ctx: Ctx) -> CancelResult:
        return await _run(ctx, service_for, lambda svc: svc.cancel(body.event_id))

    @router.post("/order_lookup", response_model_exclude_none=True)
    async def order_lookup(body: OrderLookupRequest, ctx: Ctx) -> OrderLookupResult:
        return await _run(
            ctx,
            service_for,
            lambda svc: svc.look_up_order(
                body.caller_name, body.address_or_eircode, body.order_id
            ),
        )

    return router
