"""Caps a call's length at what the organization's credit can pay for."""

from loguru import logger

from api.constants import BILLING_PROVIDER
from api.db import db_client
from api.services.billing.pricing import MIN_GUARDED_CALL_SECONDS, price_per_minute_eur
from api.services.call_concurrency import call_concurrency


async def _active_calls(organization_id: int) -> int:
    """Calls the organization has in progress, including the one starting."""
    try:
        return max(await call_concurrency.get_org_active_calls(organization_id), 1)
    except Exception:
        logger.warning(
            "Could not count active calls for organization {}; capping as if "
            "this were its only call",
            organization_id,
            exc_info=True,
        )
        return 1


async def affordable_call_seconds(organization_id: int) -> int | None:
    """Longest call the organization's spendable credit covers right now.

    Spendable credit is shared equally between the organization's calls in
    progress, so concurrent calls cannot each spend the whole balance; a call
    that starts later sees the balance its predecessors have not yet been
    charged for, so the result is a bound, not an exact reservation.

    None when calls are not billed through Stripe or are free.
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
    if available <= 0:
        return MIN_GUARDED_CALL_SECONDS
    share = available / await _active_calls(organization_id)
    return max(int(share * 60 / rate), MIN_GUARDED_CALL_SECONDS)


def capped_call_duration(configured_seconds: int, affordable: int | None) -> int:
    if affordable is None:
        return configured_seconds
    return min(configured_seconds, affordable)
