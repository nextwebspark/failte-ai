"""Request/response bodies for Stripe prepaid billing."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from api.enums import BillingLedgerEntryType, BillingPlan


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BillingAccountResponse(BaseModel):
    currency: str
    plan: BillingPlan
    balance_eur: Decimal
    credit_limit_eur: Decimal
    price_per_minute_eur: Decimal
    min_balance_for_call_eur: Decimal
    topup_packs_eur: list[Decimal]
    min_topup_eur: Decimal
    max_topup_eur: Decimal
    setup_fee_eur: Decimal
    setup_fee_included_credit_eur: Decimal
    sales_contact: str | None


class BillingLedgerEntryResponse(BaseModel):
    id: int
    entry_type: BillingLedgerEntryType
    amount_eur: Decimal
    balance_after_eur: Decimal
    description: str | None
    workflow_run_id: int | None
    created_at: datetime


class BillingLedgerResponse(BaseModel):
    entries: list[BillingLedgerEntryResponse]
    total: int
    limit: int
    offset: int


class TopUpRequest(_Request):
    amount_eur: Annotated[Decimal, Field(gt=0, max_digits=8, decimal_places=2)]


class CheckoutUrlResponse(BaseModel):
    url: str


class AdminBillingAccountResponse(BaseModel):
    organization_id: int
    plan: BillingPlan
    balance_eur: Decimal
    credit_limit_eur: Decimal
    price_per_minute_override_eur: Decimal | None
    effective_price_per_minute_eur: Decimal
    stripe_customer_id: str | None


class AdminUpdateBillingAccountRequest(_Request):
    """Only the fields present are changed; send price_per_minute_eur: null
    to drop the override and fall back to the plan's rate."""

    plan: BillingPlan | None = None
    price_per_minute_eur: Annotated[
        Decimal | None, Field(ge=0, max_digits=10, decimal_places=4)
    ] = None
    credit_limit_eur: Annotated[
        Decimal | None, Field(ge=0, max_digits=14, decimal_places=2)
    ] = None


class AdminLedgerAdjustmentRequest(_Request):
    entry_type: Literal[
        BillingLedgerEntryType.ADJUSTMENT, BillingLedgerEntryType.REFUND
    ]
    # Signed: positive credits the balance, negative debits it.
    amount_eur: Annotated[Decimal, Field(max_digits=14, decimal_places=4)]
    description: Annotated[str, Field(min_length=1, max_length=500)]
