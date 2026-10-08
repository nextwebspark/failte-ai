"""Stripe webhook receiver. Authenticated by Stripe's signature, not a login."""

from typing import Annotated

import stripe
from fastapi import APIRouter, Header, HTTPException, Request
from loguru import logger

from api.services.billing.stripe_client import construct_webhook_event
from api.services.billing.webhooks import handle_stripe_event

router = APIRouter(prefix="/billing/stripe", tags=["billing"])


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
) -> dict:
    payload = await request.body()
    try:
        event = construct_webhook_event(payload, stripe_signature)
    except (ValueError, stripe.SignatureVerificationError):
        logger.warning("Rejected Stripe webhook with an invalid signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # A handler failure propagates as a 500 so Stripe retries the delivery.
    await handle_stripe_event(event)
    return {"received": True}
