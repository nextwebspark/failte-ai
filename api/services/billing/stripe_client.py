"""Thin async wrapper around the Stripe API.

Stripe only collects money; balances live in our ledger. Everything that talks
to Stripe goes through this module so it can be replaced in tests.
"""

from functools import lru_cache

import stripe
from loguru import logger

from api.constants import STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
from api.db import db_client
from api.errors.billing import BillingNotConfiguredError


@lru_cache(maxsize=1)
def get_stripe_client() -> stripe.StripeClient:
    if not STRIPE_SECRET_KEY:
        raise BillingNotConfiguredError()
    return stripe.StripeClient(STRIPE_SECRET_KEY, http_client=stripe.HTTPXClient())


def construct_webhook_event(payload: bytes, signature: str | None) -> stripe.Event:
    """Verify a webhook's signature and parse it.

    Raises ``stripe.SignatureVerificationError`` or ``ValueError`` when the
    request did not come from Stripe.
    """
    if not STRIPE_WEBHOOK_SECRET:
        raise BillingNotConfiguredError()
    return stripe.Webhook.construct_event(payload, signature, STRIPE_WEBHOOK_SECRET)


async def ensure_stripe_customer(
    organization_id: int,
    *,
    email: str | None = None,
    name: str | None = None,
) -> str:
    """Return the organization's Stripe customer id, creating the customer once.

    Created lazily at first checkout, so organizations that never pay never
    touch Stripe. The idempotency key keeps concurrent first checkouts from
    creating two customers.
    """
    account, _ = await db_client.ensure_billing_account(organization_id)
    if account.stripe_customer_id:
        return account.stripe_customer_id

    params: dict = {"metadata": {"organization_id": str(organization_id)}}
    if email:
        params["email"] = email
    if name:
        params["name"] = name
    customer = await get_stripe_client().v1.customers.create_async(
        params=params,
        options={"idempotency_key": f"organization-{organization_id}-customer"},
    )
    customer_id = await db_client.set_billing_stripe_customer_id(
        organization_id, customer.id
    )
    logger.info(
        "Created Stripe customer {} for organization {}", customer_id, organization_id
    )
    return customer_id
