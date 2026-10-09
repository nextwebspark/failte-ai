"""Prices and limits for Stripe billing.

All amounts are EUR, excluding VAT (Stripe Tax adds VAT at checkout).
Change prices here; nothing else hard-codes them.
"""

from decimal import Decimal

from api.enums import BillingPlan

CURRENCY = "eur"

# Rate charged per minute of call time, billed per second.
DEFAULT_PRICE_PER_MINUTE_EUR = Decimal("0.12")
PLAN_PRICE_PER_MINUTE_EUR: dict[BillingPlan, Decimal] = {
    BillingPlan.PAYG: DEFAULT_PRICE_PER_MINUTE_EUR,
    BillingPlan.DONE_FOR_YOU: DEFAULT_PRICE_PER_MINUTE_EUR,
    # Enterprise accounts normally carry a negotiated override on the account.
    BillingPlan.ENTERPRISE: DEFAULT_PRICE_PER_MINUTE_EUR,
}

# Credit granted once when a billing account is created.
TRIAL_CREDIT_EUR = Decimal("5.00")

# Top-up packs offered in the UI, and the bounds for a custom amount.
TOPUP_PACKS_EUR: tuple[Decimal, ...] = (
    Decimal("20"),
    Decimal("50"),
    Decimal("100"),
    Decimal("250"),
)
MIN_TOPUP_EUR = Decimal("20")
MAX_TOPUP_EUR = Decimal("5000")

# A call may start only when balance + credit limit is at least this much
# (about four minutes at the default rate).
MIN_BALANCE_FOR_CALL_EUR = Decimal("0.50")

# Admins are emailed when spendable credit (balance + credit limit) drops
# below this, and again when it can no longer start a call.
LOW_BALANCE_WARNING_EUR = Decimal("5.00")

# A call's maximum length is capped at what the balance can pay for when it
# starts, but never below this, so a call is not cut off the moment it starts.
MIN_GUARDED_CALL_SECONDS = 60

# Done-for-you: one-time setup fee, which includes some call credit.
SETUP_FEE_EUR = Decimal("550.00")
SETUP_FEE_INCLUDED_CREDIT_EUR = Decimal("50.00")


def price_per_minute_eur(plan: BillingPlan, override: Decimal | None = None) -> Decimal:
    """Effective per-minute rate for an account."""
    if override is not None:
        return override
    return PLAN_PRICE_PER_MINUTE_EUR.get(plan, DEFAULT_PRICE_PER_MINUTE_EUR)
