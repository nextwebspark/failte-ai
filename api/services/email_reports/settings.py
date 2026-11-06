"""What a workspace asked for: which reports, when, for which agent, and to
whom. Stored as the ``EMAIL_REPORTS`` organization configuration row; the
recipient rules (who may be added without a confirmation link) are pure
functions here so they can be tested without a database.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from api.enums import OrganizationConfigurationKey
from api.services.email_reports.periods import Frequency, parse_clock
from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator

SETTINGS_KEY = OrganizationConfigurationKey.EMAIL_REPORTS.value
SENT_KEY = OrganizationConfigurationKey.EMAIL_REPORTS_SENT.value

MAX_RECIPIENTS = 10
# Kept on the row: the last changes, who made them and when.
HISTORY_LENGTH = 30
# A confirmation email can be resent this often per address.
RESEND_AFTER = timedelta(minutes=2)

RecipientStatus = Literal["active", "pending"]


class ReportRecipient(BaseModel):
    id: str
    email: str
    status: RecipientStatus
    # "account": a member's own sign-in address, verified at sign-up.
    # "link": confirmed from the emailed link.
    verified_via: Literal["account", "link"] | None = None
    added_by_user_id: int | None = None
    added_at: datetime
    confirmed_at: datetime | None = None
    # Set while pending: the confirmation link carries it, and it is cleared
    # once used, so each link works once.
    confirm_nonce: str | None = None
    confirm_sent_at: datetime | None = None


class ReportChange(BaseModel):
    at: datetime
    by_user_id: int | None
    by: str | None
    change: str


class EmailReportSettings(BaseModel):
    daily: bool = False
    weekly: bool = False
    monthly: bool = False
    daily_send_time: str = "18:00"
    # None: every agent in the workspace.
    workflow_id: int | None = None
    recipients: list[ReportRecipient] = Field(default_factory=list)
    history: list[ReportChange] = Field(default_factory=list)

    @field_validator("daily_send_time")
    @classmethod
    def _clock(cls, value: str) -> str:
        parse_clock(value)
        return value

    def enabled(self, frequency: Frequency) -> bool:
        return bool(getattr(self, frequency.value))

    def active_recipients(self) -> list[ReportRecipient]:
        return [r for r in self.recipients if r.status == "active"]

    def find(self, recipient_id: str) -> ReportRecipient | None:
        return next((r for r in self.recipients if r.id == recipient_id), None)

    def find_email(self, address: str) -> ReportRecipient | None:
        key = normalise_email(address)
        return next(
            (r for r in self.recipients if normalise_email(r.email) == key), None
        )


def parse_settings(
    value: Any, organization_id: int | None = None
) -> EmailReportSettings:
    if not isinstance(value, dict) or not value:
        return EmailReportSettings()
    try:
        return EmailReportSettings.model_validate(value)
    except ValidationError as exc:
        logger.warning(
            f"Invalid email report settings for organization {organization_id}: "
            f"{exc.error_count()} error(s). Using defaults."
        )
        return EmailReportSettings()


def normalise_email(address: str) -> str:
    return address.strip().casefold()


def new_recipient_id() -> str:
    return secrets.token_urlsafe(9)


def new_nonce() -> str:
    return secrets.token_urlsafe(18)


class RecipientError(ValueError):
    pass


def add_recipient(
    settings: EmailReportSettings,
    *,
    address: str,
    by_user_id: int,
    own_verified_email: str | None,
    now: datetime,
) -> ReportRecipient:
    """Add ``address``. It is active straight away only when it is the
    member's own verified sign-in address; any other address starts pending
    and gets nothing until its link is used. Mutates ``settings``."""
    address = address.strip()
    if settings.find_email(address) is not None:
        raise RecipientError("That address is already on the list.")
    if len(settings.recipients) >= MAX_RECIPIENTS:
        raise RecipientError(
            f"You can send reports to at most {MAX_RECIPIENTS} addresses."
        )
    own = own_verified_email is not None and normalise_email(
        own_verified_email
    ) == normalise_email(address)
    recipient = ReportRecipient(
        id=new_recipient_id(),
        email=address,
        status="active" if own else "pending",
        verified_via="account" if own else None,
        added_by_user_id=by_user_id,
        added_at=now,
        confirmed_at=now if own else None,
        confirm_nonce=None if own else new_nonce(),
        confirm_sent_at=None if own else now,
    )
    settings.recipients.append(recipient)
    return recipient


def refresh_confirmation(
    settings: EmailReportSettings, recipient_id: str, now: datetime
) -> ReportRecipient:
    """A new link for a pending address (the old one stops working)."""
    recipient = settings.find(recipient_id)
    if recipient is None:
        raise RecipientError("That address isn't on the list any more.")
    if recipient.status != "pending":
        raise RecipientError("That address is already confirmed.")
    if recipient.confirm_sent_at and now - recipient.confirm_sent_at < RESEND_AFTER:
        raise RecipientError("We just sent it. Give it a couple of minutes.")
    recipient.confirm_nonce = new_nonce()
    recipient.confirm_sent_at = now
    return recipient


def confirm_recipient(
    settings: EmailReportSettings,
    recipient_id: str,
    *,
    email_matches,
    now: datetime,
) -> Literal["confirmed", "already", "invalid"]:
    """Use a confirmation link. ``email_matches(recipient)`` checks the link's
    address hash and nonce. Mutates ``settings``."""
    recipient = settings.find(recipient_id)
    if recipient is None:
        return "invalid"
    if recipient.status == "active":
        return "already" if email_matches(recipient, None) else "invalid"
    if recipient.confirm_nonce is None or not email_matches(
        recipient, recipient.confirm_nonce
    ):
        return "invalid"
    recipient.status = "active"
    recipient.verified_via = "link"
    recipient.confirmed_at = now
    recipient.confirm_nonce = None
    return "confirmed"


def remove_recipient(
    settings: EmailReportSettings, recipient_id: str
) -> ReportRecipient | None:
    recipient = settings.find(recipient_id)
    if recipient is not None:
        settings.recipients = [r for r in settings.recipients if r.id != recipient_id]
    return recipient


def record_change(
    settings: EmailReportSettings,
    *,
    by_user_id: int | None,
    by: str | None,
    change: str,
    now: datetime | None = None,
) -> None:
    settings.history.append(
        ReportChange(
            at=now or datetime.now(UTC), by_user_id=by_user_id, by=by, change=change
        )
    )
    settings.history = settings.history[-HISTORY_LENGTH:]


def describe_changes(
    before: EmailReportSettings, after: EmailReportSettings
) -> list[str]:
    """Plain words for what a settings save changed (for the history)."""
    changes: list[str] = []
    for frequency in Frequency:
        was, now = before.enabled(frequency), after.enabled(frequency)
        if was != now:
            changes.append(f"{frequency.value} report {'on' if now else 'off'}")
    if before.daily_send_time != after.daily_send_time:
        changes.append(
            f"daily time {before.daily_send_time} -> {after.daily_send_time}"
        )
    if before.workflow_id != after.workflow_id:
        changes.append(
            f"agent {before.workflow_id or 'all'} -> {after.workflow_id or 'all'}"
        )
    return changes
