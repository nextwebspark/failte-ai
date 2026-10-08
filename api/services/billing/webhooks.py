"""Handling of verified Stripe webhook events."""

from collections.abc import Awaitable, Callable

import stripe
from loguru import logger

from api.services.billing.checkout import handle_paid_checkout_session

EventHandler = Callable[[stripe.Event], Awaitable[None]]

# Event type -> handler. Every handler must be idempotent: Stripe delivers at
# least once and retries anything that did not get a 2xx.
_HANDLERS: dict[str, EventHandler] = {
    "checkout.session.completed": handle_paid_checkout_session,
    "checkout.session.async_payment_succeeded": handle_paid_checkout_session,
}


async def handle_stripe_event(event: stripe.Event) -> None:
    handler = _HANDLERS.get(event.type)
    if handler is None:
        logger.debug("Ignoring Stripe event {} ({})", event.id, event.type)
        return
    logger.info("Handling Stripe event {} ({})", event.id, event.type)
    await handler(event)
