"""Superuser billing administration: plans, negotiated rates, credit limits
and manual ledger adjustments (e.g. Enterprise invoices paid outside the
app)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from api.db import db_client
from api.db.billing_client import BillingAccount
from api.db.models import UserModel
from api.routes.billing import require_stripe_billing
from api.schemas.billing import (
    AdminBillingAccountResponse,
    AdminLedgerAdjustmentRequest,
    AdminUpdateBillingAccountRequest,
    BillingLedgerEntryResponse,
)
from api.services.auth.depends import get_superuser
from api.services.billing.accounts import ensure_billing_account
from api.services.billing.pricing import price_per_minute_eur

router = APIRouter(
    prefix="/superuser/billing",
    tags=["superuser"],
    dependencies=[Depends(require_stripe_billing)],
)

Superuser = Annotated[UserModel, Depends(get_superuser)]


async def _require_organization(organization_id: int) -> None:
    if await db_client.get_organization_by_id(organization_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")


def _to_response(account: BillingAccount) -> AdminBillingAccountResponse:
    return AdminBillingAccountResponse(
        organization_id=account.organization_id,
        plan=account.plan,
        balance_eur=account.balance_eur,
        credit_limit_eur=account.credit_limit_eur,
        price_per_minute_override_eur=account.price_per_minute_eur,
        effective_price_per_minute_eur=price_per_minute_eur(
            account.plan, account.price_per_minute_eur
        ),
        stripe_customer_id=account.stripe_customer_id,
    )


@router.get(
    "/organizations/{organization_id}",
    response_model=AdminBillingAccountResponse,
    include_in_schema=False,
)
async def get_organization_billing(
    organization_id: int, _user: Superuser
) -> AdminBillingAccountResponse:
    await _require_organization(organization_id)
    return _to_response(await ensure_billing_account(organization_id))


@router.patch(
    "/organizations/{organization_id}",
    response_model=AdminBillingAccountResponse,
    include_in_schema=False,
)
async def update_organization_billing(
    organization_id: int, body: AdminUpdateBillingAccountRequest, _user: Superuser
) -> AdminBillingAccountResponse:
    await _require_organization(organization_id)
    await ensure_billing_account(organization_id)
    changes = body.model_dump(include=body.model_fields_set)
    for field in ("plan", "credit_limit_eur"):
        if field in changes and changes[field] is None:
            raise HTTPException(status_code=422, detail=f"{field} cannot be null")
    account = await db_client.update_billing_account(organization_id, **changes)
    return _to_response(account)


@router.post(
    "/organizations/{organization_id}/adjustments",
    response_model=BillingLedgerEntryResponse,
    include_in_schema=False,
)
async def adjust_organization_balance(
    organization_id: int, body: AdminLedgerAdjustmentRequest, user: Superuser
) -> BillingLedgerEntryResponse:
    await _require_organization(organization_id)
    await ensure_billing_account(organization_id)
    entry = await db_client.add_billing_ledger_entry(
        organization_id=organization_id,
        entry_type=body.entry_type,
        amount_eur=body.amount_eur,
        description=body.description,
        created_by=user.id,
    )
    return BillingLedgerEntryResponse(
        id=entry.id,
        entry_type=entry.entry_type,
        amount_eur=entry.amount_eur,
        balance_after_eur=entry.balance_after_eur,
        description=entry.description,
        workflow_run_id=entry.workflow_run_id,
        created_at=entry.created_at,
    )
