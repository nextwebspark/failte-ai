"""Request/response bodies for Stripe prepaid billing."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

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
