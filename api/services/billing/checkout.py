"""Stripe Checkout for prepaid credit top-ups."""

from decimal import ROUND_HALF_UP, Decimal

import stripe
from loguru import logger

from api.constants import STRIPE_AUTOMATIC_TAX, UI_APP_URL
from api.db import db_client
from api.enums import BillingLedgerEntryType
from api.errors.billing import InvalidTopUpAmountError
from api.services.billing.accounts import ensure_billing_account
from api.services.billing.pricing import CURRENCY, MAX_TOPUP_EUR, MIN_TOPUP_EUR
from api.services.billing.stripe_client import (
    ensure_stripe_customer,
    get_stripe_client,
)

# Checkout session metadata["purpose"] values.
PURPOSE_TOPUP = "topup"

_CENT = Decimal("0.01")


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


async def create_portal_session(organization_id: int) -> str:
    """Stripe Customer Portal link, where customers download their invoices."""
    customer_id = await ensure_stripe_customer(organization_id)
    session = await get_stripe_client().v1.billing_portal.sessions.create_async(
        params={"customer": customer_id, "return_url": _billing_url("portal=return")},
    )
    return session.url


async def handle_paid_checkout_session(event: stripe.Event) -> None:
    """Credit the wallet for a paid top-up. Safe to run more than once."""
    session = event.data.object
    if session.payment_status != "paid":
        # Delayed payment methods finish later with async_payment_succeeded.
        return

    metadata = session.metadata.to_dict() if session.metadata else {}
    if metadata.get("purpose") != PURPOSE_TOPUP:
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

    # Credit the VAT-exclusive amount; VAT is owed to Revenue, not spendable.
    amount_eur = _from_cents(session.amount_subtotal)
    created_by = metadata.get("created_by")
    entry = await db_client.add_billing_ledger_entry(
        organization_id=organization_id,
        entry_type=BillingLedgerEntryType.TOPUP,
        amount_eur=amount_eur,
        description="Credit top-up",
        stripe_checkout_session_id=session.id,
        created_by=int(created_by) if created_by else None,
        metadata={"payment_intent": session.payment_intent},
    )
    if entry is None:
        logger.info("Checkout session {} was already credited", session.id)
        return
    logger.info(
        "Credited EUR {} to organization {} from checkout session {}",
        amount_eur,
        organization_id,
        session.id,
    )
