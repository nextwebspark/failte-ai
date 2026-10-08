"""Billing account lifecycle."""

from loguru import logger

from api.db import db_client
from api.db.billing_client import BillingAccount
from api.enums import BillingLedgerEntryType
from api.services.billing.pricing import TRIAL_CREDIT_EUR


async def ensure_billing_account(organization_id: int) -> BillingAccount:
    """Return the organization's billing account, creating it on first use.

    A new account starts with the trial credit. Accounts are created lazily so
    organizations that predate Stripe billing get one the first time they need
    it.
    """
    account, created = await db_client.ensure_billing_account(organization_id)
    if not created or TRIAL_CREDIT_EUR <= 0:
        return account

    await db_client.add_billing_ledger_entry(
        organization_id=organization_id,
        entry_type=BillingLedgerEntryType.TRIAL_CREDIT,
        amount_eur=TRIAL_CREDIT_EUR,
        description="Welcome credit",
    )
    logger.info(
        "Granted EUR {} trial credit to organization {}",
        TRIAL_CREDIT_EUR,
        organization_id,
    )
    return await db_client.get_billing_account(organization_id)
