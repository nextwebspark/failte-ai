"""Narrow storage interfaces the invitation service depends on.

``api.db.db_client`` satisfies both structurally; tests pass in fakes.
"""

from datetime import datetime
from typing import Protocol

from api.db.invitation_client import Invitation
from api.db.membership_client import OrganizationSummary, UserIdentity
from api.enums import OrgRole


class InvitationStore(Protocol):
    async def create_invitation(
        self,
        *,
        organization_id: int,
        email: str,
        role: OrgRole,
        token_hash: str,
        invited_by: int | None,
        expires_at: datetime,
        now: datetime,
    ) -> Invitation: ...

    async def count_invitations_created_since(
        self, organization_id: int, since: datetime
    ) -> int: ...

    async def list_open_invitations(
        self, organization_id: int, now: datetime
    ) -> list[Invitation]: ...

    async def list_open_invitations_for_email(
        self, email: str, now: datetime
    ) -> list[Invitation]: ...

    async def get_invitation(
        self, organization_id: int, invitation_id: int
    ) -> Invitation | None: ...

    async def get_invitation_by_token_hash(
        self, token_hash: str
    ) -> Invitation | None: ...

    async def revoke_invitation(
        self, organization_id: int, invitation_id: int, now: datetime
    ) -> bool: ...

    async def rotate_invitation_token(
        self,
        organization_id: int,
        invitation_id: int,
        *,
        token_hash: str,
        expires_at: datetime,
    ) -> Invitation | None: ...

    async def accept_invitation(
        self,
        invitation_id: int,
        *,
        user_id: int,
        now: datetime,
        select_organization: bool,
    ) -> Invitation: ...


class Directory(Protocol):
    async def get_user_identity(self, user_id: int) -> UserIdentity | None: ...

    async def get_user_identity_by_email(self, email: str) -> UserIdentity | None: ...

    async def get_organization_summary(
        self, organization_id: int
    ) -> OrganizationSummary | None: ...

    async def get_member_role(
        self, user_id: int, organization_id: int
    ) -> OrgRole | None: ...
