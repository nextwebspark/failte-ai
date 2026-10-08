"""Organization members, switching, and invitation management."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from api.db import db_client
from api.db.invitation_client import Invitation
from api.db.models import UserModel
from api.enums import OrgRole
from api.schemas.team import (
    CreateInvitationRequest,
    CreateOrganizationRequest,
    InvitationResponse,
    IssuedInvitationResponse,
    MemberResponse,
    RenameOrganizationRequest,
    UpdateMemberRoleRequest,
    UserOrganizationResponse,
)
from api.services.auth.depends import (
    OrgMembership,
    get_org_membership,
    get_user,
    require_local_auth,
    require_permission,
)
from api.services.auth.permissions import Permission
from api.services.invitations import (
    InvitationService,
    IssuedInvitation,
    get_invitation_service,
)
from api.services.membership import (
    create_organization_for_user,
    leave_organization,
    select_organization,
)
from api.utils.clock import SystemClock

router = APIRouter(prefix="/organizations", tags=["team"])

# Under Stack Auth, team membership is owned by Stack (its team invitations and
# member removal); our membership rows follow it. Endpoints that add or remove
# members therefore only exist with local auth, or a member removed here would
# be re-added from their Stack team on their next request.
LOCAL_MEMBERSHIP = [Depends(require_local_auth)]

MembersReader = Annotated[
    OrgMembership, Depends(require_permission(Permission.MEMBERS_READ))
]
MembersManager = Annotated[
    OrgMembership, Depends(require_permission(Permission.MEMBERS_MANAGE))
]
Invitations = Annotated[InvitationService, Depends(get_invitation_service)]


def _invitation_response(invitation: Invitation) -> InvitationResponse:
    return InvitationResponse(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        status=invitation.status(SystemClock().now()),
        invited_by=invitation.invited_by,
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
    )


def _issued_response(issued: IssuedInvitation) -> IssuedInvitationResponse:
    return IssuedInvitationResponse(
        invitation=_invitation_response(issued.invitation),
        email_sent=issued.email_sent,
        accept_url=issued.accept_url,
    )


# -- the caller's organizations ----------------------------------------------


@router.get("/mine", response_model=list[UserOrganizationResponse])
async def list_my_organizations(
    user: Annotated[UserModel, Depends(get_user)],
) -> list[UserOrganizationResponse]:
    organizations = await db_client.list_user_organizations(user.id)
    return [
        UserOrganizationResponse(
            organization_id=o.organization_id,
            name=o.name,
            role=o.role,
            is_selected=o.organization_id == user.selected_organization_id,
        )
        for o in organizations
    ]


@router.post(
    "",
    response_model=UserOrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_local_auth)],
)
async def create_organization(
    request: CreateOrganizationRequest,
    user: Annotated[UserModel, Depends(get_user)],
) -> UserOrganizationResponse:
    organization_id = await create_organization_for_user(
        user_id=user.id, user_provider_id=user.provider_id, name=request.name
    )
    return UserOrganizationResponse(
        organization_id=organization_id,
        name=request.name,
        role=OrgRole.ADMIN,
        is_selected=True,
    )


@router.post(
    "/{organization_id}/select",
    status_code=status.HTTP_204_NO_CONTENT,
    # Under Stack Auth the selected team drives the organization instead.
    dependencies=[Depends(require_local_auth)],
)
async def select_my_organization(
    organization_id: int,
    user: Annotated[UserModel, Depends(get_user)],
) -> Response:
    await select_organization(user_id=user.id, organization_id=organization_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/current", status_code=status.HTTP_204_NO_CONTENT)
async def rename_current_organization(
    request: RenameOrganizationRequest,
    membership: Annotated[
        OrgMembership, Depends(require_permission(Permission.ORG_MANAGE))
    ],
) -> Response:
    await db_client.update_organization_name(membership.organization_id, request.name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/leave", status_code=status.HTTP_204_NO_CONTENT, dependencies=LOCAL_MEMBERSHIP
)
async def leave_current_organization(
    membership: Annotated[OrgMembership, Depends(get_org_membership)],
) -> Response:
    await leave_organization(
        user_id=membership.user.id, organization_id=membership.organization_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- members -------------------------------------------------------------------


@router.get("/members", response_model=list[MemberResponse])
async def list_members(membership: MembersReader) -> list[MemberResponse]:
    members = await db_client.list_organization_members(membership.organization_id)
    return [
        MemberResponse(
            user_id=m.user_id,
            email=m.email,
            name=m.name,
            role=m.role,
            joined_at=m.joined_at,
            is_current_user=m.user_id == membership.user.id,
        )
        for m in members
    ]


@router.patch("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_member_role(
    user_id: int, request: UpdateMemberRoleRequest, membership: MembersManager
) -> Response:
    await db_client.update_member_role(
        membership.organization_id, user_id, request.role
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=LOCAL_MEMBERSHIP,
)
async def remove_member(user_id: int, membership: MembersManager) -> Response:
    if user_id == membership.user.id:
        raise HTTPException(
            status_code=400, detail="Use 'leave organization' to remove yourself"
        )
    await db_client.remove_organization_member(membership.organization_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- invitations ---------------------------------------------------------------


@router.get(
    "/invitations",
    response_model=list[InvitationResponse],
    dependencies=LOCAL_MEMBERSHIP,
)
async def list_invitations(
    membership: MembersManager, invitations: Invitations
) -> list[InvitationResponse]:
    pending = await invitations.list_open(membership.organization_id)
    return [_invitation_response(i) for i in pending]


@router.post(
    "/invitations",
    response_model=IssuedInvitationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=LOCAL_MEMBERSHIP,
)
async def create_invitation(
    request: CreateInvitationRequest,
    membership: MembersManager,
    invitations: Invitations,
) -> IssuedInvitationResponse:
    issued = await invitations.invite(
        organization_id=membership.organization_id,
        inviter_id=membership.user.id,
        email=request.email,
        role=request.role,
    )
    return _issued_response(issued)


@router.post(
    "/invitations/{invitation_id}/resend",
    response_model=IssuedInvitationResponse,
    dependencies=LOCAL_MEMBERSHIP,
)
async def resend_invitation(
    invitation_id: int, membership: MembersManager, invitations: Invitations
) -> IssuedInvitationResponse:
    issued = await invitations.resend(
        organization_id=membership.organization_id,
        invitation_id=invitation_id,
        inviter_id=membership.user.id,
    )
    return _issued_response(issued)


@router.delete(
    "/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=LOCAL_MEMBERSHIP,
)
async def revoke_invitation(
    invitation_id: int, membership: MembersManager, invitations: Invitations
) -> Response:
    await invitations.revoke(
        organization_id=membership.organization_id, invitation_id=invitation_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
