"""Stripe Checkout for prepaid credit top-ups."""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import stripe
from loguru import logger

from api.constants import STRIPE_AUTOMATIC_TAX, UI_APP_URL
from api.db import db_client
from api.enums import BillingLedgerEntryType, BillingPlan
from api.errors.billing import (
    CheckoutRateLimitError,
    InvalidTopUpAmountError,
    SetupFeeNotAvailableError,
)
from api.services.billing.accounts import ensure_billing_account
from api.services.billing.pricing import (
    CURRENCY,
    MAX_TOPUP_EUR,
    MIN_TOPUP_EUR,
    SETUP_FEE_EUR,
    SETUP_FEE_INCLUDED_CREDIT_EUR,
)
from api.services.billing.stripe_client import (
    ensure_stripe_customer,
    get_stripe_client,
)
from api.services.rate_limit import get_rate_limiter

# Checkout session metadata["purpose"] values.
PURPOSE_TOPUP = "topup"
PURPOSE_SETUP_FEE = "setup_fee"

_CENT = Decimal("0.01")

# Checkout sessions an organization may open per window; each one is a Stripe
# API call, so this keeps a stuck button or a script from hammering Stripe.
CHECKOUT_RATE_LIMIT = 10
CHECKOUT_RATE_WINDOW = timedelta(minutes=10)


def _billing_url(query: str) -> str:
    return f"{UI_APP_URL.rstrip('/')}/billing?{query}"


def _to_cents(amount_eur: Decimal) -> int:
    return int((amount_eur * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _from_cents(cents: int) -> Decimal:
    return (Decimal(cents) / 100).quantize(_CENT)


async def create_checkout_session(
    *,
    organization_id: int,
    customer_email: str | None,
    amount_eur: Decimal,
    product_name: str,
    purpose: str,
    created_by: int,
) -> str:
    """Create a one-off Checkout session and return its URL.

    Prices are VAT-exclusive; with automatic tax on, Stripe adds Irish VAT, or
    reverse-charges it when an EU business enters a valid VAT number. Stripe
    emails the customer an invoice for every payment.
    """
    if not await get_rate_limiter().allow(
        f"billing-checkout:{organization_id}",
        limit=CHECKOUT_RATE_LIMIT,
        window=CHECKOUT_RATE_WINDOW,
    ):
        raise CheckoutRateLimitError()
    await ensure_billing_account(organization_id)
    organization = await db_client.get_organization_by_id(organization_id)
    customer_id = await ensure_stripe_customer(
        organization_id,
        email=customer_email,
        name=organization.name if organization else None,
    )
    metadata = {
        "organization_id": str(organization_id),
        "purpose": purpose,
        "created_by": str(created_by),
    }
    session = await get_stripe_client().v1.checkout.sessions.create_async(
        params={
            "mode": "payment",
            "customer": customer_id,
            "line_items": [
                {
                    "price_data": {
                        "currency": CURRENCY,
                        "unit_amount": _to_cents(amount_eur),
                        "tax_behavior": "exclusive",
                        "product_data": {"name": product_name},
                    },
                    "quantity": 1,
                }
            ],
            "automatic_tax": {"enabled": STRIPE_AUTOMATIC_TAX},
            "tax_id_collection": {"enabled": True},
            "billing_address_collection": "required",
            "customer_update": {"address": "auto", "name": "auto"},
            "invoice_creation": {"enabled": True},
            "metadata": metadata,
            "payment_intent_data": {"metadata": metadata},
            "success_url": _billing_url("checkout=success"),
            "cancel_url": _billing_url("checkout=cancelled"),
        },
    )
    return session.url


async def create_topup_checkout(
    *,
    organization_id: int,
    customer_email: str | None,
    amount_eur: Decimal,
    created_by: int,
) -> str:
    if amount_eur != amount_eur.quantize(_CENT) or not (
        MIN_TOPUP_EUR <= amount_eur <= MAX_TOPUP_EUR
    ):
        raise InvalidTopUpAmountError(
            f"Top-up must be between EUR {MIN_TOPUP_EUR} and EUR {MAX_TOPUP_EUR}"
        )
    return await create_checkout_session(
        organization_id=organization_id,
        customer_email=customer_email,
        amount_eur=amount_eur,
        product_name="Fáilte AI call credit",
        purpose=PURPOSE_TOPUP,
        created_by=created_by,
    )


async def create_setup_fee_checkout(
    *,
    organization_id: int,
    customer_email: str | None,
    created_by: int,
) -> str:
    """Checkout for the one-time Done-for-you setup fee.

    Only pay-as-you-go accounts can buy it; Done-for-you accounts have
    already paid it, and Enterprise terms are agreed separately.
    """
    account = await ensure_billing_account(organization_id)
    if account.plan != BillingPlan.PAYG:
        raise SetupFeeNotAvailableError(account.plan)
    return await create_checkout_session(
        organization_id=organization_id,
        customer_email=customer_email,
        amount_eur=SETUP_FEE_EUR,
        product_name="Fáilte AI done-for-you agent setup",
        purpose=PURPOSE_SETUP_FEE,
        created_by=created_by,
    )


async def create_portal_session(organization_id: int) -> str:
    """Stripe Customer Portal link, where customers download their invoices."""
    customer_id = await ensure_stripe_customer(organization_id)
    session = await get_stripe_client().v1.billing_portal.sessions.create_async(
        params={"customer": customer_id, "return_url": _billing_url("portal=return")},
    )
    return session.url


async def handle_paid_checkout_session(event: stripe.Event) -> None:
    """Apply a paid Checkout session to the ledger. Safe to run more than once."""
    session = event.data.object
    if session.payment_status != "paid":
        # Delayed payment methods finish later with async_payment_succeeded.
        return

    metadata = session.metadata.to_dict() if session.metadata else {}
    purpose = metadata.get("purpose")
    if purpose not in (PURPOSE_TOPUP, PURPOSE_SETUP_FEE):
        return

    organization_id = int(metadata["organization_id"])
    account = await db_client.get_billing_account(organization_id)
    if account is None or account.stripe_customer_id != session.customer:
        logger.error(
            "Checkout session {} names organization {} but its customer {} is "
            "not that organization's; not crediting",
            session.id,
            organization_id,
            session.customer,
        )
        return

    # VAT-exclusive amount paid; VAT is owed to Revenue, never spendable.
    paid_eur = _from_cents(session.amount_subtotal)
    created_by = metadata.get("created_by")
    if purpose == PURPOSE_TOPUP:
        entry_type = BillingLedgerEntryType.TOPUP
        credit_eur = paid_eur
        description = "Credit top-up"
    else:
        # The fee pays for our work; only its included call credit is spendable.
        entry_type = BillingLedgerEntryType.SETUP_FEE
        credit_eur = SETUP_FEE_INCLUDED_CREDIT_EUR
        description = "Done-for-you setup (includes call credit)"

    entry = await db_client.add_billing_ledger_entry(
        organization_id=organization_id,
        entry_type=entry_type,
        amount_eur=credit_eur,
        description=description,
        stripe_checkout_session_id=session.id,
        created_by=int(created_by) if created_by else None,
        metadata={
            "payment_intent": session.payment_intent,
            "paid_eur": str(paid_eur),
            # VAT-inclusive total in cents, to size later refunds and disputes.
            "amount_total": session.amount_total,
        },
    )
    # Before the duplicate check returns: if the plan change failed after the
    # ledger entry committed, Stripe's retry must still apply it.
    if purpose == PURPOSE_SETUP_FEE and account.plan == BillingPlan.PAYG:
        await db_client.update_billing_account(
            organization_id, plan=BillingPlan.DONE_FOR_YOU
        )
    if entry is None:
        logger.info("Checkout session {} was already applied", session.id)
        return

    logger.info(
        "Applied {} checkout session {} to organization {}: paid EUR {}, "
        "credited EUR {}",
        purpose,
        session.id,
        organization_id,
        paid_eur,
        credit_eur,
    )
