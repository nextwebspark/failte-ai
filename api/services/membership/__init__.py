"""Organization creation, switching and leaving for an individual user."""

import uuid

from api.db import db_client
from api.enums import OrgRole
from api.errors.membership import OrganizationAccessDeniedError
from api.services.organization_bootstrap import ensure_organization_bootstrapped


async def create_organization_for_user(
    *, user_id: int, user_provider_id: str, name: str | None
) -> int:
    """Create an organization administered by ``user_id`` and select it.

    Returns the new organization's id.
    """
    organization, _ = await db_client.get_or_create_organization_by_provider_id(
        org_provider_id=f"org_{uuid.uuid4().hex}", user_id=user_id
    )
    organization_id: int = organization.id
    if name:
        await db_client.update_organization_name(organization_id, name)
    await db_client.add_user_to_organization(
        user_id, organization_id, role=OrgRole.ADMIN
    )
    await db_client.update_user_selected_organization(user_id, organization_id)
    # Never raises; auth re-enters bootstrap on later requests if it fails.
    await ensure_organization_bootstrapped(organization_id, created_by=user_provider_id)
    return organization_id


async def select_organization(*, user_id: int, organization_id: int) -> None:
    if await db_client.get_member_role(user_id, organization_id) is None:
        raise OrganizationAccessDeniedError()
    await db_client.update_user_selected_organization(user_id, organization_id)


async def leave_organization(*, user_id: int, organization_id: int) -> int | None:
    """Remove the user from the organization and select another one they
    belong to, if any. Returns the newly selected organization id."""
    await db_client.remove_organization_member(organization_id, user_id)
    remaining = await db_client.list_user_organizations(user_id)
    if not remaining:
        return None
    next_id = remaining[0].organization_id
    await db_client.update_user_selected_organization(user_id, next_id)
    return next_id
