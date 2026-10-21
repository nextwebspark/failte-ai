"""Requesting, cancelling and enforcing organisation deletion (GDPR Art. 17).

A request closes the organisation at once and schedules its erasure
``ORG_DELETION_GRACE_DAYS`` later (``org_erasure`` carries it out). While it is
pending:

* the API refuses every organisation-scoped request (``ensure_organization_open``,
  called from ``api.services.auth.depends``) except the export, the deletion
  status and the cancel, so admins can still take their data and change their
  mind;
* API keys, widget tokens, agent triggers and running campaigns are switched
  off, and no new call starts (``organization_accepts_calls``).
"""

from datetime import UTC, datetime, timedelta
from typing import Optional

from api import constants
from api.db import db_client
from api.db.org_erasure_client import OrganizationDeletionState
from api.errors.privacy import (
    ConfirmationMismatchError,
    OrganizationDeletionNotPendingError,
    OrganizationErasedError,
    OrganizationErasureStartedError,
    OrganizationPendingDeletionError,
)


def _confirmation_matches(expected: Optional[str], given: str) -> bool:
    return bool(expected) and given.strip().casefold() == expected.strip().casefold()


async def get_organization_deletion_state(
    organization_id: int,
) -> Optional[OrganizationDeletionState]:
    return await db_client.get_organization_deletion_state(organization_id)


async def ensure_organization_open(organization_id: int) -> None:
    """Raise unless the organisation is usable (not pending deletion or erased)."""
    state = await db_client.get_organization_deletion_state(organization_id)
    if state is None:
        return
    if state.is_erased:
        raise OrganizationErasedError()
    if state.is_pending:
        raise OrganizationPendingDeletionError(state.scheduled_for)


async def organization_accepts_calls(organization_id: int) -> bool:
    """False while the organisation is pending deletion or erased."""
    state = await db_client.get_organization_deletion_state(organization_id)
    return state is None or not (state.is_pending or state.is_erased)


async def request_organization_deletion(
    organization_id: int,
    *,
    confirm_name: str,
    now: Optional[datetime] = None,
) -> OrganizationDeletionState:
    """Schedule the organisation's erasure; ``confirm_name`` must be its name.

    A repeated request keeps the original schedule.
    """
    state = await db_client.get_organization_deletion_state(organization_id)
    if state is None or state.is_erased:
        raise OrganizationErasedError()
    expected = state.name or f"organization {organization_id}"
    if not _confirmation_matches(expected, confirm_name):
        raise ConfirmationMismatchError(
            "Type the organization's name exactly to confirm the deletion."
        )
    now = now or datetime.now(UTC)
    scheduled = await db_client.request_organization_deletion(
        organization_id,
        requested_at=now,
        scheduled_for=now + timedelta(days=constants.ORG_DELETION_GRACE_DAYS),
    )
    if scheduled is None:
        raise OrganizationErasedError()
    return scheduled


async def cancel_organization_deletion(
    organization_id: int, *, now: Optional[datetime] = None
) -> OrganizationDeletionState:
    now = now or datetime.now(UTC)
    state = await db_client.get_organization_deletion_state(organization_id)
    if state is None or state.is_erased:
        raise OrganizationErasedError()
    if not state.is_pending:
        raise OrganizationDeletionNotPendingError()
    if state.scheduled_for is not None and state.scheduled_for <= now:
        # The erasure cron may already be deleting stored objects.
        raise OrganizationErasureStartedError()
    cancelled = await db_client.cancel_organization_deletion(
        organization_id, cancelled_at=now
    )
    if cancelled is None:
        raise OrganizationDeletionNotPendingError()
    return cancelled
