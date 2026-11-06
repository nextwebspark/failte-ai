"""Per-organization notification settings, stored as an organization
configuration row (``CALL_NOTIFICATIONS``)."""

from __future__ import annotations

from loguru import logger
from pydantic import ValidationError

from api.db import db_client
from api.enums import OrganizationConfigurationKey, OrgRole
from api.schemas.call_notifications import CallNotificationSettings

CONFIG_KEY = OrganizationConfigurationKey.CALL_NOTIFICATIONS.value

# Who gets the business emails by default. "viewer" is shown as Owner.
MEMBER_RECIPIENT_ROLES = frozenset({OrgRole.ADMIN, OrgRole.VIEWER})


async def load_notification_settings(
    organization_id: int, db=None
) -> CallNotificationSettings:
    """The stored settings, or the defaults when none are stored. An
    unreadable row falls back to the defaults with a warning."""
    row = await (db or db_client).get_configuration(organization_id, CONFIG_KEY)
    value = row.value if row is not None else None
    if not isinstance(value, dict):
        return CallNotificationSettings()
    try:
        return CallNotificationSettings.model_validate(value)
    except ValidationError as exc:
        logger.warning(
            f"Invalid call notification settings for organization "
            f"{organization_id}: {exc.error_count()} error(s). Using defaults."
        )
        return CallNotificationSettings()


async def save_notification_settings(
    organization_id: int, settings: CallNotificationSettings
) -> CallNotificationSettings:
    await db_client.upsert_configuration(
        organization_id, CONFIG_KEY, settings.model_dump(mode="json")
    )
    return settings


async def member_recipients(organization_id: int, db=None) -> list[str]:
    """The owners' and admins' email addresses, in membership order."""
    members = await (db or db_client).list_organization_members(organization_id)
    return [
        member.email
        for member in members
        if member.role in MEMBER_RECIPIENT_ROLES and member.email
    ]


def email_recipients(
    settings: CallNotificationSettings, members: list[str]
) -> list[str]:
    """Everyone who gets the business email, each address once."""
    addresses = [
        *(members if settings.email_members else []),
        *settings.extra_recipients,
    ]
    seen: set[str] = set()
    unique = []
    for address in addresses:
        key = address.strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(address.strip())
    return unique
