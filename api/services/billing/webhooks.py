"""Handling of verified Stripe webhook events."""

from collections.abc import Awaitable, Callable

import stripe
from loguru import logger

EventHandler = Callable[[stripe.Event], Awaitable[None]]

# Event type -> handler. Every handler must be idempotent: Stripe delivers at
# least once and retries anything that did not get a 2xx.
_HANDLERS: dict[str, EventHandler] = {}


async def handle_stripe_event(event: stripe.Event) -> None:
    handler = _HANDLERS.get(event.type)
    if handler is None:
        logger.debug("Ignoring Stripe event {} ({})", event.id, event.type)
        return
    logger.info("Handling Stripe event {} ({})", event.id, event.type)
    await handler(event)
