"""Request/response bodies for organization members, switching and invitations."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, StringConstraints

from api.enums import InvitationStatus, OrgRole

OrganizationName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemberResponse(BaseModel):
    user_id: int
    email: str | None
    name: str | None
    role: OrgRole
    joined_at: datetime | None
    is_current_user: bool


class UpdateMemberRoleRequest(_Request):
    role: OrgRole


class UserOrganizationResponse(BaseModel):
    organization_id: int
    name: str | None
    role: OrgRole
    is_selected: bool


class CreateOrganizationRequest(_Request):
    name: OrganizationName


class RenameOrganizationRequest(_Request):
    name: OrganizationName


class CreateInvitationRequest(_Request):
    email: EmailStr
    role: OrgRole


class InvitationResponse(BaseModel):
    id: int
    email: str
    role: OrgRole
    status: InvitationStatus
    invited_by: int | None
    created_at: datetime
    expires_at: datetime


class IssuedInvitationResponse(BaseModel):
    invitation: InvitationResponse
    email_sent: bool
    # Present only when the email was not delivered, so the admin can share
    # the link themselves.
    accept_url: str | None = None


class InvitationPreviewResponse(BaseModel):
    organization_name: str
    inviter_name: str | None
    role: OrgRole
    email: str
    status: InvitationStatus


class AcceptInvitationRequest(_Request):
    token: str


class AcceptInvitationResponse(BaseModel):
    organization_id: int
