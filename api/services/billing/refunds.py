"""Take credit back when a Stripe payment is refunded or disputed."""

from decimal import ROUND_HALF_UP, Decimal

import stripe
from loguru import logger

from api.db import db_client
from api.db.billing_client import BillingLedgerEntry
from api.enums import BillingLedgerEntryType

_QUANTUM = Decimal("0.0001")


def _share(credited: Decimal, part_cents: int, whole_cents: int | None) -> Decimal:
    """The part of a payment's credit that ``part_cents`` of it represents."""
    if not whole_cents:
        return credited
    fraction = min(Decimal(part_cents) / Decimal(whole_cents), Decimal(1))
    return (credited * fraction).quantize(_QUANTUM, rounding=ROUND_HALF_UP)


async def _credit_for(
    payment_intent: str | None, source: str
) -> BillingLedgerEntry | None:
    credit = (
        await db_client.get_paid_ledger_entry_for_payment_intent(payment_intent)
        if payment_intent
        else None
    )
    if credit is None:
        logger.warning(
            "No credited payment found for {} (payment intent {}); nothing to reverse",
            source,
            payment_intent,
        )
    return credit


async def handle_charge_refunded(event: stripe.Event) -> None:
    """Debit the refunded share of a top-up or setup-fee credit.

    ``amount_refunded`` is cumulative, so each delivery debits only what is not
    yet debited for this charge; the reference makes a redelivery a no-op.
    """
    charge = event.data.object
    credit = await _credit_for(charge.payment_intent, f"refunded charge {charge.id}")
    if credit is None:
        return

    target = _share(credit.amount_eur, charge.amount_refunded, charge.amount)
    already = -await db_client.sum_ledger_entries_with_reference_prefix(
        credit.organization_id, f"{charge.id}:refund:"
    )
    debit = target - already
    if debit <= 0:
        return
    await db_client.add_billing_ledger_entry(
        organization_id=credit.organization_id,
        entry_type=BillingLedgerEntryType.REFUND,
        amount_eur=-debit,
        description="Payment refunded",
        stripe_reference=f"{charge.id}:refund:{charge.amount_refunded}",
        metadata={"payment_intent": charge.payment_intent, "charge": charge.id},
    )
    logger.info(
        "Debited EUR {} from organization {} for refund of charge {}",
        debit,
        credit.organization_id,
        charge.id,
    )


async def handle_dispute_created(event: stripe.Event) -> None:
    """Hold back the disputed share of the credit while the bank decides."""
    dispute = event.data.object
    credit = await _credit_for(dispute.payment_intent, f"dispute {dispute.id}")
    if credit is None:
        return

    debit = _share(
        credit.amount_eur, dispute.amount, credit.metadata.get("amount_total")
    )
    await db_client.add_billing_ledger_entry(
        organization_id=credit.organization_id,
        entry_type=BillingLedgerEntryType.REFUND,
        amount_eur=-debit,
        description="Payment disputed",
        stripe_reference=f"{dispute.id}:dispute",
        metadata={"payment_intent": dispute.payment_intent, "dispute": dispute.id},
    )
    logger.warning(
        "Debited EUR {} from organization {} for dispute {}",
        debit,
        credit.organization_id,
        dispute.id,
    )


async def handle_dispute_closed(event: stripe.Event) -> None:
    """Give the held-back credit back when a dispute is won."""
    dispute = event.data.object
    if dispute.status != "won":
        return
    credit = await _credit_for(dispute.payment_intent, f"dispute {dispute.id}")
    if credit is None:
        return

    held_back = -await db_client.sum_ledger_entries_with_reference_prefix(
        credit.organization_id, f"{dispute.id}:dispute"
    )
    if held_back <= 0:
        return
    await db_client.add_billing_ledger_entry(
        organization_id=credit.organization_id,
        entry_type=BillingLedgerEntryType.ADJUSTMENT,
        amount_eur=held_back,
        description="Dispute won; credit restored",
        stripe_reference=f"{dispute.id}:won",
        metadata={"payment_intent": dispute.payment_intent, "dispute": dispute.id},
    )
    logger.info(
        "Restored EUR {} to organization {} after winning dispute {}",
        held_back,
        credit.organization_id,
        dispute.id,
    )
