"""Prepaid credit balance, ledger, top-ups and invoices (Stripe billing)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from api.constants import BILLING_PROVIDER
from api.db import db_client
from api.enums import BillingLedgerEntryType
from api.schemas.billing import (
    BillingAccountResponse,
    BillingLedgerEntryResponse,
    BillingLedgerResponse,
    CheckoutUrlResponse,
    TopUpRequest,
)
from api.services.auth.depends import OrgMembership, require_permission
from api.services.auth.permissions import Permission
from api.services.billing import pricing
from api.services.billing.accounts import ensure_billing_account
from api.services.billing.checkout import create_portal_session, create_topup_checkout


async def require_stripe_billing() -> None:
    if BILLING_PROVIDER != "stripe":
        raise HTTPException(status_code=404, detail="Billing is not enabled")


router = APIRouter(
    prefix="/billing",
    tags=["billing"],
    dependencies=[Depends(require_stripe_billing)],
)

BillingReader = Annotated[
    OrgMembership, Depends(require_permission(Permission.BILLING_READ))
]
BillingManager = Annotated[
    OrgMembership, Depends(require_permission(Permission.BILLING_MANAGE))
]


@router.get("/account", response_model=BillingAccountResponse)
async def get_billing_account(membership: BillingReader) -> BillingAccountResponse:
    account = await ensure_billing_account(membership.organization_id)
    return BillingAccountResponse(
        currency=pricing.CURRENCY,
        plan=account.plan,
        balance_eur=account.balance_eur,
        credit_limit_eur=account.credit_limit_eur,
        price_per_minute_eur=pricing.price_per_minute_eur(
            account.plan, account.price_per_minute_eur
        ),
        min_balance_for_call_eur=pricing.MIN_BALANCE_FOR_CALL_EUR,
        topup_packs_eur=list(pricing.TOPUP_PACKS_EUR),
        min_topup_eur=pricing.MIN_TOPUP_EUR,
        max_topup_eur=pricing.MAX_TOPUP_EUR,
        setup_fee_eur=pricing.SETUP_FEE_EUR,
        setup_fee_included_credit_eur=pricing.SETUP_FEE_INCLUDED_CREDIT_EUR,
    )


@router.get("/ledger", response_model=BillingLedgerResponse)
async def get_billing_ledger(
    membership: BillingReader,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    entry_type: BillingLedgerEntryType | None = None,
) -> BillingLedgerResponse:
    entries, total = await db_client.list_billing_ledger_entries(
        membership.organization_id,
        limit=limit,
        offset=offset,
        entry_type=entry_type,
    )
    return BillingLedgerResponse(
        entries=[
            BillingLedgerEntryResponse(
                id=entry.id,
                entry_type=entry.entry_type,
                amount_eur=entry.amount_eur,
                balance_after_eur=entry.balance_after_eur,
                description=entry.description,
                workflow_run_id=entry.workflow_run_id,
                created_at=entry.created_at,
            )
            for entry in entries
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/top-up", response_model=CheckoutUrlResponse)
async def create_top_up(
    body: TopUpRequest, membership: BillingManager
) -> CheckoutUrlResponse:
    url = await create_topup_checkout(
        organization_id=membership.organization_id,
        customer_email=membership.user.email,
        amount_eur=body.amount_eur,
        created_by=membership.user.id,
    )
    return CheckoutUrlResponse(url=url)


@router.post("/portal", response_model=CheckoutUrlResponse)
async def create_billing_portal(membership: BillingManager) -> CheckoutUrlResponse:
    url = await create_portal_session(membership.organization_id)
    return CheckoutUrlResponse(url=url)
