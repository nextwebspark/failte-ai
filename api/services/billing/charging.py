"""Per-call charging against the prepaid credit ledger."""

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from loguru import logger

from api.db import db_client
from api.enums import BillingLedgerEntryType
from api.services.billing.accounts import ensure_billing_account
from api.services.billing.notifications import notify_balance_change
from api.services.billing.pricing import price_per_minute_eur

_LEDGER_QUANTUM = Decimal("0.0001")


def billable_seconds(usage_info: dict[str, Any] | None) -> int:
    """Whole seconds to bill, rounding any part second up."""
    duration = (usage_info or {}).get("call_duration_seconds")
    try:
        seconds = float(duration)
    except (TypeError, ValueError):
        return 0
    return math.ceil(seconds) if seconds > 0 else 0


def call_charge_eur(seconds: int, rate_per_minute_eur: Decimal) -> Decimal:
    return (rate_per_minute_eur * seconds / 60).quantize(
        _LEDGER_QUANTUM, rounding=ROUND_HALF_UP
    )


async def charge_workflow_run(workflow_run, organization_id: int) -> None:
    """Debit a completed call from its organization's balance.

    Idempotent per run: the ledger refuses a second usage entry for the same
    run, so a retried completion job never double-charges. Calls that never
    connected (no duration) are free.
    """
    seconds = billable_seconds(getattr(workflow_run, "usage_info", None))
    if seconds == 0:
        logger.info("Not charging workflow run {}: no call time", workflow_run.id)
        return

    account = await ensure_billing_account(organization_id)
    rate = price_per_minute_eur(account.plan, account.price_per_minute_eur)
    amount = call_charge_eur(seconds, rate)
    entry = await db_client.add_billing_ledger_entry(
        organization_id=organization_id,
        entry_type=BillingLedgerEntryType.USAGE,
        amount_eur=-amount,
        description=f"Call {workflow_run.id}: {seconds}s at EUR {rate}/min",
        workflow_run_id=workflow_run.id,
        metadata={"billed_seconds": seconds, "rate_per_minute_eur": str(rate)},
    )
    if entry is None:
        logger.info("Workflow run {} was already charged", workflow_run.id)
        return

    await db_client.update_workflow_run(
        workflow_run.id,
        cost_info={
            **(getattr(workflow_run, "cost_info", None) or {}),
            "currency": "EUR",
            "billed_seconds": seconds,
            "rate_per_minute_eur": str(rate),
            "charge_eur": str(amount),
        },
    )
    try:
        await notify_balance_change(
            organization_id,
            available_before=entry.balance_after_eur
            - entry.amount_eur
            + account.credit_limit_eur,
            available_after=entry.balance_after_eur + account.credit_limit_eur,
            balance_after=entry.balance_after_eur,
        )
    except Exception:
        logger.warning(
            "Failed to send balance alert for organization {}",
            organization_id,
            exc_info=True,
        )
    logger.info(
        "Charged EUR {} to organization {} for workflow run {} ({}s); balance EUR {}",
        amount,
        organization_id,
        workflow_run.id,
        seconds,
        entry.balance_after_eur,
    )
