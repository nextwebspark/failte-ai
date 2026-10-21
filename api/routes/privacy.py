"""Data-subject rights: export and delete your account or your organization."""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from api.db.models import UserModel
from api.db.org_erasure_client import OrganizationDeletionState
from api.schemas.privacy import (
    DeleteAccountRequest,
    DeleteOrganizationRequest,
    OrganizationDeletionStatus,
)
from api.services.auth.depends import (
    OrgMembership,
    get_user,
    require_permission,
)
from api.services.auth.permissions import Permission
from api.services.privacy.account_deletion import delete_user_account
from api.services.privacy.data_export import (
    export_organization_data,
    export_user_data,
)
from api.services.privacy.org_deletion import (
    cancel_organization_deletion,
    get_organization_deletion_state,
    request_organization_deletion,
)

router = APIRouter(tags=["privacy"])

# These stay open while the organization is pending deletion, so admins can
# still take their data and change their mind.
OrgAdminDuringDeletion = Annotated[
    OrgMembership,
    Depends(require_permission(Permission.ORG_MANAGE, allow_pending_deletion=True)),
]
OrgMemberDuringDeletion = Annotated[
    OrgMembership, Depends(require_permission(allow_pending_deletion=True))
]

_JSON_DOWNLOAD = {
    200: {
        "description": "A JSON document, sent as a file download.",
        "content": {"application/json": {"schema": {"type": "object"}}},
    }
}


def _download(document: dict[str, Any], name: str) -> JSONResponse:
    filename = f"{name}-{datetime.now(UTC):%Y-%m-%d}.json"
    return JSONResponse(
        content=jsonable_encoder(document),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


def deletion_status(
    state: OrganizationDeletionState | None,
) -> OrganizationDeletionStatus:
    if state is None or not state.is_pending:
        return OrganizationDeletionStatus(pending=False)
    return OrganizationDeletionStatus(
        pending=True,
        requested_at=state.requested_at,
        scheduled_for=state.scheduled_for,
    )


# -- your account --------------------------------------------------------------


@router.get("/user/me/export", responses=_JSON_DOWNLOAD)
async def export_my_data(user: Annotated[UserModel, Depends(get_user)]) -> JSONResponse:
    """Download your profile, organization memberships and onboarding progress."""
    return _download(await export_user_data(user), "lightmove-account")


@router.delete("/user/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account(
    request: DeleteAccountRequest,
    user: Annotated[UserModel, Depends(get_user)],
) -> Response:
    """Permanently delete your account.

    Refused (409) while you are the only admin of an organization that has
    other members (``last_admin_of_organization``) or the only member of an
    organization (``sole_member_of_organization``): delete that organization
    first. What you created stays with your organizations.
    """
    await delete_user_account(user, confirm_email=request.confirm_email)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- your organization --------------------------------------------------------


@router.get("/organizations/export", responses=_JSON_DOWNLOAD)
async def export_organization(membership: OrgAdminDuringDeletion) -> JSONResponse:
    """Download the organization's settings, members, agents, tools, campaigns,
    knowledge base list, phone numbers and billing ledger. Secrets and call
    content are not included."""
    return _download(
        await export_organization_data(membership.organization_id),
        f"lightmove-organization-{membership.organization_id}",
    )


@router.get("/organizations/deletion", response_model=OrganizationDeletionStatus)
async def get_organization_deletion(
    membership: OrgMemberDuringDeletion,
) -> OrganizationDeletionStatus:
    return deletion_status(
        await get_organization_deletion_state(membership.organization_id)
    )


@router.post("/organizations/deletion", response_model=OrganizationDeletionStatus)
async def delete_organization(
    request: DeleteOrganizationRequest, membership: OrgAdminDuringDeletion
) -> OrganizationDeletionStatus:
    """Schedule the organization for permanent erasure in 30 days.

    It is closed at once: API keys, widget tokens, agent triggers and running
    campaigns are switched off, calls to its numbers are refused, and its API
    answers 423 (``organization_pending_deletion``) except for the export, this
    status and the cancel.
    """
    state = await request_organization_deletion(
        membership.organization_id, confirm_name=request.confirm_name
    )
    return deletion_status(state)


@router.delete("/organizations/deletion", response_model=OrganizationDeletionStatus)
async def cancel_organization_deletion_request(
    membership: OrgAdminDuringDeletion,
) -> OrganizationDeletionStatus:
    """Cancel a pending deletion and switch back on what it switched off."""
    state = await cancel_organization_deletion(membership.organization_id)
    return deletion_status(state)
