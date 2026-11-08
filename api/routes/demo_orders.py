"""Sample orders of demo workspaces: the agent's order lookup and the owner's
read-only list. See ``api/services/demo_orders.py`` for the rules."""

from __future__ import annotations

from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Header, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from api.constants import REDIS_URL
from api.db import db_client
from api.enums import OrgRole
from api.services import demo_orders
from api.services.auth.depends import OrgMembership, require_permission
from api.services.auth.permissions import Permission

router = APIRouter(prefix="/demo/sample-orders", tags=["demo"])

# Failed checks are counted per call for this long.
FAILURE_WINDOW_SECONDS = 2 * 60 * 60

_redis: aioredis.Redis | None = None


def _client() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(  # type: ignore[no-untyped-call]
            REDIS_URL, decode_responses=True, socket_timeout=2, socket_connect_timeout=2
        )
    return _redis


def _failures_key(organization_id: int, run_id: int) -> str:
    return f"demo-order-lookup-failures:{organization_id}:{run_id}"


class LookupRequest(BaseModel):
    order_number: str = Field(default="", max_length=40)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    caller_name: str | None = Field(default=None, max_length=120)
    # The call (workflow run) the lookup is made on, filled in by the tool.
    call_ref: str = Field(default="", max_length=20)


async def _demo_orders(organization_id: int) -> dict[str, Any] | None:
    """The workspace's sample orders, only when it is a marked demo one."""
    if (
        await db_client.get_configuration(organization_id, demo_orders.DEMO_ACCOUNT_KEY)
        is None
    ):
        return None
    row = await db_client.get_configuration(
        organization_id, demo_orders.SAMPLE_ORDERS_KEY
    )
    value = row.value if row else None
    return value if isinstance(value, dict) else None


async def _run_in_organization(run_id: int, organization_id: int) -> bool:
    run, run_org = await db_client.get_workflow_run_with_context(run_id)
    return run is not None and run_org == organization_id


@router.post("/lookup", summary="Look up a sample order (demo workspaces only)")
async def lookup_order(
    request: LookupRequest,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    key = demo_orders.bearer(authorization)
    organization_id = demo_orders.organization_of_key(key)
    stored = await _demo_orders(organization_id) if organization_id else None
    if (
        organization_id is None
        or stored is None
        or not demo_orders.same_key(key, str(stored.get("lookup_key") or ""))
    ):
        raise HTTPException(status_code=401, detail="Unknown lookup key")
    if not request.call_ref.isdigit() or not await _run_in_organization(
        int(request.call_ref), organization_id
    ):
        # Every lookup belongs to a call, so failed checks can be counted.
        raise HTTPException(status_code=400, detail="Unknown call")
    run_id = int(request.call_ref)
    failures_key = _failures_key(organization_id, run_id)
    try:
        failures = int(await _client().get(failures_key) or 0)
    except RedisError as exc:
        logger.warning(f"Order lookup: failure count unavailable ({exc})")
        raise HTTPException(status_code=503, detail="Lookup unavailable") from exc
    if failures >= demo_orders.MAX_FAILURES:
        return demo_orders.refusal(locked=True)
    if not demo_orders.order_key(request.order_number) or not (
        (request.email or "").strip() or (request.phone or "").strip()
    ):
        # Nothing to check yet: not a failed attempt.
        return demo_orders.refusal(locked=False, missing=True)
    result = demo_orders.check(
        list(stored.get("orders") or []),
        order_number=request.order_number,
        email=request.email,
        phone=request.phone,
        caller_name=request.caller_name,
    )
    if result.verified and result.order is not None:
        logger.info(f"Order lookup verified on run {run_id}")
        return demo_orders.answer(result.order)
    try:
        async with _client().pipeline(transaction=True) as pipe:
            pipe.incr(failures_key)
            pipe.expire(failures_key, FAILURE_WINDOW_SECONDS)
            failures = int((await pipe.execute())[0])
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Lookup unavailable") from exc
    logger.info(f"Order lookup not verified on run {run_id} ({result.reason})")
    return demo_orders.refusal(locked=failures >= demo_orders.MAX_FAILURES)


class SampleOrdersView(BaseModel):
    available: bool
    note: str | None = None
    orders: list[dict[str, Any]] = Field(default_factory=list)


@router.get(
    "",
    response_model=SampleOrdersView,
    summary="The demo workspace's sample orders (owner view)",
)
async def list_sample_orders(
    membership: Annotated[
        OrgMembership, Depends(require_permission(Permission.AGENTS_READ))
    ],
) -> SampleOrdersView:
    """Only the owner or an admin of a marked demo workspace sees anything; everyone
    else (and every real workspace) gets ``available: false``."""
    if membership.role not in (OrgRole.ADMIN, OrgRole.VIEWER):
        return SampleOrdersView(available=False)
    stored = await _demo_orders(membership.organization_id)
    if not stored:
        return SampleOrdersView(available=False)
    return SampleOrdersView(
        available=True,
        note=stored.get("note"),
        orders=demo_orders.public_rows(list(stored.get("orders") or [])),
    )
