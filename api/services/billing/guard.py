"""Caps a call's length at what the organization's credit can pay for."""

from api.constants import BILLING_PROVIDER
from api.db import db_client
from api.services.billing.pricing import MIN_GUARDED_CALL_SECONDS, price_per_minute_eur


async def affordable_call_seconds(organization_id: int) -> int | None:
    """Longest call the organization's spendable credit covers right now.

    None when calls are not billed through Stripe or are free. Concurrent
    calls each see the full balance, so the balance can still dip slightly
    below zero; the cap bounds how far.
    """
    if BILLING_PROVIDER != "stripe":
        return None
    account = await db_client.get_billing_account(organization_id)
    if account is None:
        return None
    rate = price_per_minute_eur(account.plan, account.price_per_minute_eur)
    if rate <= 0:
        return None
    available = account.balance_eur + account.credit_limit_eur
    seconds = int(available * 60 / rate) if available > 0 else 0
    return max(seconds, MIN_GUARDED_CALL_SECONDS)


def capped_call_duration(configured_seconds: int, affordable: int | None) -> int:
    if affordable is None:
        return configured_seconds
    return min(configured_seconds, affordable)
