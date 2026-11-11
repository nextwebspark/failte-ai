"""Support tickets from the in-app Help panel.

Stored on the workspace's configuration row (no migration), like custom voice
requests, emailed to the support team (SUPPORT_EMAILS, else
OPERATOR_ALERT_EMAILS) and confirmed to the person who sent it. Statuses are
changed by the team by hand; the panel only shows them.
"""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime
from html import escape
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, Field, field_validator

from api.constants import BRAND_SUPPORT_EMAIL
from api.db import db_client
from api.enums import OrganizationConfigurationKey
from api.services.help_assistant.knowledge import normalise_page

TICKETS_KEY = OrganizationConfigurationKey.SUPPORT_TICKETS.value
# Kept per workspace; older ones drop off the panel (the emails remain).
MAX_STORED = 200

TicketCategory = Literal[
    "setup", "phone", "billing", "bug", "feature", "privacy", "other"
]
CATEGORY_LABELS: dict[str, str] = {
    "setup": "Setup help",
    "phone": "Phone or transfers",
    "billing": "Billing",
    "bug": "Bug report",
    "feature": "Feature request",
    "privacy": "Privacy",
    "other": "Other",
}
TicketStatus = Literal["open", "answered", "closed"]


class TicketIn(BaseModel):
    category: TicketCategory
    subject: str = Field(min_length=1, max_length=150)
    message: str = Field(min_length=1, max_length=4000)
    include_page: bool = False
    page: str | None = Field(default=None, max_length=300)

    @field_validator("subject", "message")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Please fill this in.")
        return value


class Ticket(BaseModel):
    reference: str
    category: TicketCategory
    subject: str
    message: str
    page: str | None = None
    workspace_name: str | None = None
    created_by_user_id: int
    created_by_email: str | None = None
    created_at: datetime
    status: TicketStatus = "open"


class TicketSummary(BaseModel):
    """What the panel lists (the message stays in the email and the store)."""

    reference: str
    category: TicketCategory
    subject: str
    created_at: datetime
    status: TicketStatus


def support_recipients(env: dict[str, str] | None = None) -> list[str]:
    env = env if env is not None else dict(os.environ)
    raw = (
        env.get("SUPPORT_EMAILS")
        or env.get("OPERATOR_ALERT_EMAILS")
        or BRAND_SUPPORT_EMAIL
    )
    return [part.strip() for part in raw.split(",") if part.strip()]


async def _stored(organization_id: int) -> list[dict[str, Any]]:
    row = await db_client.get_configuration(organization_id, TICKETS_KEY)
    value = row.value if row is not None else None
    items = value.get("tickets") if isinstance(value, dict) else None
    return list(items) if isinstance(items, list) else []


def new_reference(taken: set[str]) -> str:
    """LM- and four digits; five once a workspace has used many of them."""
    for digits in (4, 4, 4, 5, 5, 6, 6):
        ref = f"LM-{secrets.randbelow(9 * 10 ** (digits - 1)) + 10 ** (digits - 1)}"
        if ref not in taken:
            return ref
    return f"LM-{secrets.token_hex(4).upper()}"


async def list_tickets(
    organization_id: int, user_id: int, limit: int = 10
) -> list[TicketSummary]:
    out: list[TicketSummary] = []
    for item in reversed(await _stored(organization_id)):
        if not isinstance(item, dict) or item.get("created_by_user_id") != user_id:
            continue
        try:
            out.append(TicketSummary.model_validate(item))
        except ValueError:
            continue
        if len(out) >= limit:
            break
    return out


async def create_ticket(
    *,
    organization_id: int,
    organization_name: str | None,
    user_id: int,
    user_email: str | None,
    body: TicketIn,
    now: datetime | None = None,
) -> Ticket:
    items = await _stored(organization_id)
    taken = {str(item.get("reference")) for item in items if isinstance(item, dict)}
    ticket = Ticket(
        reference=new_reference(taken),
        category=body.category,
        subject=body.subject,
        message=body.message,
        page=normalise_page(body.page) if body.include_page else None,
        workspace_name=organization_name if body.include_page else None,
        created_by_user_id=user_id,
        created_by_email=user_email,
        created_at=now or datetime.now(UTC),
    )
    items.append(ticket.model_dump(mode="json"))
    await db_client.upsert_configuration(
        organization_id, TICKETS_KEY, {"tickets": items[-MAX_STORED:]}
    )
    logger.info(
        f"support ticket {ticket.reference} org={organization_id} "
        f"user={user_id} category={ticket.category}"
    )
    await _notify(ticket, organization_id, organization_name)
    return ticket


def team_email_lines(
    ticket: Ticket, organization_id: int, organization_name: str | None
) -> list[str]:
    return [
        f"Reference: {ticket.reference}",
        f"Category: {CATEGORY_LABELS[ticket.category]}",
        f"Workspace: {organization_name or '-'} (id {organization_id})",
        f"From: {ticket.created_by_email or '-'} (user id {ticket.created_by_user_id})",
        f"Page: {ticket.page or 'not shared'}",
        f"Subject: {ticket.subject}",
        "",
        ticket.message,
    ]


def confirmation_lines(ticket: Ticket) -> list[str]:
    return [
        (
            "Thanks for getting in touch. We've got your message and a person "
            "from the LightMove team will reply to this email address."
        ),
        "",
        f"Your reference: {ticket.reference}",
        f"Topic: {CATEGORY_LABELS[ticket.category]}",
        f"Subject: {ticket.subject}",
        "",
        (
            "If you need to add anything, reply to this email and keep the "
            "reference in the subject."
        ),
    ]


def _html(lines: list[str]) -> str:
    return "".join(
        f"<p>{escape(line).replace(chr(10), '<br>')}</p>" if line else ""
        for line in lines
    )


async def _notify(
    ticket: Ticket, organization_id: int, organization_name: str | None
) -> None:
    """Email the team and the sender. Never raises: the ticket is stored."""
    from api.services.email import get_email_sender
    from api.services.email.base import EmailMessage

    sender = get_email_sender()
    recipients = support_recipients()
    if not recipients:
        logger.warning(
            f"Support ticket {ticket.reference} stored, but no SUPPORT_EMAILS or "
            "OPERATOR_ALERT_EMAILS is set, so the team wasn't emailed"
        )
    lines = team_email_lines(ticket, organization_id, organization_name)
    headers = (
        (("Reply-To", ticket.created_by_email),) if ticket.created_by_email else ()
    )
    messages = [
        EmailMessage(
            to=to,
            subject=f"[{ticket.reference}] {CATEGORY_LABELS[ticket.category]}: {ticket.subject}",
            text="\n".join(lines) + "\n",
            html=_html(lines),
            idempotency_key=f"ticket-{organization_id}-{ticket.reference}-{to}",
            headers=headers,
        )
        for to in recipients
    ]
    if ticket.created_by_email:
        confirm = confirmation_lines(ticket)
        messages.append(
            EmailMessage(
                to=ticket.created_by_email,
                subject=f"We've got your message [{ticket.reference}]",
                text="\n".join(confirm) + "\n",
                html=_html(confirm),
                idempotency_key=f"ticket-{organization_id}-{ticket.reference}-confirm",
            )
        )
    for message in messages:
        try:
            await sender.send(message)
        except Exception as exc:  # noqa: BLE001 - the ticket is stored either way
            logger.warning(
                f"Could not email support ticket {ticket.reference}: {type(exc).__name__}"
            )
