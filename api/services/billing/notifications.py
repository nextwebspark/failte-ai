"""Balance alerts emailed to organization admins."""

from decimal import Decimal

from loguru import logger

from api.constants import UI_APP_URL
from api.db import db_client
from api.enums import OrgRole
from api.services.billing.pricing import (
    LOW_BALANCE_WARNING_EUR,
    MIN_BALANCE_FOR_CALL_EUR,
)
from api.services.email import get_email_sender
from api.services.email.templates import low_balance_message

_euro = "EUR {:,.2f}".format


def crossed_threshold(before: Decimal, after: Decimal) -> str | None:
    """Which alert a balance change crosses into, if any.

    Comparing the balance either side of one ledger entry means each alert is
    sent once per crossing: it fires again only after a top-up lifts the
    balance back above the threshold and usage brings it down again.
    """
    if before >= MIN_BALANCE_FOR_CALL_EUR > after:
        return "out_of_credit"
    if before >= LOW_BALANCE_WARNING_EUR > after:
        return "low_balance"
    return None


async def notify_balance_change(
    organization_id: int,
    *,
    available_before: Decimal,
    available_after: Decimal,
) -> None:
    """Email the organization's admins when spendable credit (balance plus
    any credit limit) crosses a threshold. The email states that spendable
    amount, never the raw balance, which can be negative under a credit
    limit."""
    alert = crossed_threshold(available_before, available_after)
    if alert is None:
        return

    organization = await db_client.get_organization_by_id(organization_id)
    organization_name = (organization.name if organization else None) or "Your team"
    members = await db_client.list_organization_members(organization_id)
    recipients = [m.email for m in members if m.role == OrgRole.ADMIN and m.email]
    if not recipients:
        logger.warning(
            "No admin email to send {} alert for organization {}",
            alert,
            organization_id,
        )
        return

    sender = get_email_sender()
    for recipient in recipients:
        try:
            await sender.send(
                low_balance_message(
                    to=recipient,
                    organization_name=organization_name,
                    balance=_euro(max(available_after, Decimal(0))),
                    out_of_credit=alert == "out_of_credit",
                    billing_url=f"{UI_APP_URL.rstrip('/')}/billing",
                )
            )
        except Exception:
            logger.warning(
                "Failed to email {} alert for organization {}",
                alert,
                organization_id,
                exc_info=True,
            )
    logger.info(
        "Sent {} alert for organization {} to {} admin(s)",
        alert,
        organization_id,
        len(recipients),
    )
