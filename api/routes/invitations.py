"""Invitee-facing invitation endpoints (preview is public; accept needs login)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from api.db.models import UserModel
from api.schemas.team import (
    AcceptInvitationRequest,
    AcceptInvitationResponse,
    InvitationPreviewResponse,
)
from api.services.auth.depends import get_user
from api.services.invitations import InvitationService, get_invitation_service

router = APIRouter(prefix="/invitations", tags=["team"])

Invitations = Annotated[InvitationService, Depends(get_invitation_service)]


@router.get("/lookup", response_model=InvitationPreviewResponse)
async def preview_invitation(
    invitations: Invitations,
    token: Annotated[str, Query(min_length=16, max_length=256)],
) -> InvitationPreviewResponse:
    preview = await invitations.preview(token)
    return InvitationPreviewResponse(
        organization_id=preview.organization_id,
        organization_name=preview.organization_name,
        inviter_name=preview.inviter_name,
        role=preview.role,
        email=preview.email,
        status=preview.status,
    )


@router.post("/accept", response_model=AcceptInvitationResponse)
async def accept_invitation(
    request: AcceptInvitationRequest,
    user: Annotated[UserModel, Depends(get_user)],
    invitations: Invitations,
) -> AcceptInvitationResponse:
    if not user.email:
        raise HTTPException(status_code=400, detail="Your account has no email")
    invitation = await invitations.accept(
        token=request.token, user_id=user.id, email=user.email
    )
    return AcceptInvitationResponse(organization_id=invitation.organization_id)
