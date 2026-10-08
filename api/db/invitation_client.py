"""Data access for organization invitations."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.sql.elements import ColumnElement

from api.db.base_client import BaseDBClient
from api.db.models import (
    OrganizationInvitationModel,
    UserModel,
    organization_users_association,
)
from api.enums import InvitationStatus, OrgRole
from api.errors.invitations import InvitationNotFoundError, InvitationNotUsableError

_Invite = OrganizationInvitationModel


@dataclass(frozen=True, slots=True)
class Invitation:
    id: int
    organization_id: int
    email: str
    role: OrgRole
    invited_by: int | None
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None

    def status(self, now: datetime) -> InvitationStatus:
        if self.accepted_at is not None:
            return InvitationStatus.ACCEPTED
        if self.revoked_at is not None:
            return InvitationStatus.REVOKED
        if self.expires_at <= now:
            return InvitationStatus.EXPIRED
        return InvitationStatus.PENDING


def _to_invitation(row: OrganizationInvitationModel) -> Invitation:
    return Invitation(
        id=row.id,
        organization_id=row.organization_id,
        email=row.email,
        role=OrgRole(row.role),
        invited_by=row.invited_by,
        created_at=row.created_at,
        expires_at=row.expires_at,
        accepted_at=row.accepted_at,
        revoked_at=row.revoked_at,
    )


def _open() -> ColumnElement[bool]:
    return and_(_Invite.accepted_at.is_(None), _Invite.revoked_at.is_(None))


class InvitationClient(BaseDBClient):
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
    ) -> Invitation:
        """Create an invitation, revoking any open one for the same address.

        Concurrent invites to the same address (double-click, two admins) are
        serialized by a transaction-scoped advisory lock, so the second one
        revokes the first instead of colliding on the open-invitation index.
        """
        async with self.async_session() as session:
            await session.execute(
                select(
                    func.pg_advisory_xact_lock(
                        func.hashtextextended(
                            f"organization_invitation:{organization_id}:{email.lower()}",
                            0,
                        )
                    )
                )
            )
            await session.execute(
                update(_Invite)
                .where(
                    _Invite.organization_id == organization_id,
                    _Invite.email == email.lower(),
                    _open(),
                )
                .values(revoked_at=now)
            )
            row = OrganizationInvitationModel(
                organization_id=organization_id,
                email=email.lower(),
                role=role.value,
                token_hash=token_hash,
                invited_by=invited_by,
                created_at=now,
                expires_at=expires_at,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _to_invitation(row)

    async def count_invitations_created_since(
        self, organization_id: int, since: datetime
    ) -> int:
        async with self.async_session() as session:
            result = await session.execute(
                select(func.count())
                .select_from(_Invite)
                .where(
                    _Invite.organization_id == organization_id,
                    _Invite.created_at >= since,
                )
            )
            return int(result.scalar_one())

    async def list_open_invitations(
        self, organization_id: int, now: datetime
    ) -> list[Invitation]:
        """Invitations that can still be accepted, newest first."""
        async with self.async_session() as session:
            result = await session.execute(
                select(_Invite)
                .where(
                    _Invite.organization_id == organization_id,
                    _open(),
                    _Invite.expires_at > now,
                )
                .order_by(_Invite.created_at.desc())
            )
            return [_to_invitation(row) for row in result.scalars().all()]

    async def list_open_invitations_for_email(
        self, email: str, now: datetime
    ) -> list[Invitation]:
        """Acceptable invitations addressed to ``email`` across all orgs,
        oldest first."""
        async with self.async_session() as session:
            result = await session.execute(
                select(_Invite)
                .where(
                    _Invite.email == email.lower(),
                    _open(),
                    _Invite.expires_at > now,
                )
                .order_by(_Invite.created_at)
            )
            return [_to_invitation(row) for row in result.scalars().all()]

    async def get_invitation(
        self, organization_id: int, invitation_id: int
    ) -> Invitation | None:
        async with self.async_session() as session:
            row = await session.scalar(
                select(_Invite).where(
                    _Invite.id == invitation_id,
                    _Invite.organization_id == organization_id,
                )
            )
            return _to_invitation(row) if row else None

    async def get_invitation_by_token_hash(self, token_hash: str) -> Invitation | None:
        async with self.async_session() as session:
            row = await session.scalar(
                select(_Invite).where(_Invite.token_hash == token_hash)
            )
            return _to_invitation(row) if row else None

    async def revoke_invitation(
        self, organization_id: int, invitation_id: int, now: datetime
    ) -> bool:
        async with self.async_session() as session:
            result = await session.execute(
                update(_Invite)
                .where(
                    _Invite.id == invitation_id,
                    _Invite.organization_id == organization_id,
                    _open(),
                )
                .values(revoked_at=now)
            )
            await session.commit()
            return bool(result.rowcount)

    async def rotate_invitation_token(
        self,
        organization_id: int,
        invitation_id: int,
        *,
        token_hash: str,
        expires_at: datetime,
    ) -> Invitation | None:
        """Give an open invitation a fresh token and expiry (resend).

        The previous token stops working because only one hash is stored.
        """
        async with self.async_session() as session:
            row = await session.scalar(
                update(_Invite)
                .where(
                    _Invite.id == invitation_id,
                    _Invite.organization_id == organization_id,
                    _open(),
                )
                .values(token_hash=token_hash, expires_at=expires_at)
                .returning(_Invite)
            )
            await session.commit()
            return _to_invitation(row) if row else None

    async def accept_invitation(
        self,
        invitation_id: int,
        *,
        user_id: int,
        now: datetime,
        select_organization: bool,
    ) -> Invitation:
        """Atomically consume an invitation and grant its membership.

        An existing membership keeps its current role.

        Raises:
            InvitationNotFoundError: no such invitation.
            InvitationNotUsableError: already accepted, revoked, or expired.
        """
        async with self.async_session() as session:
            row = await self._lock_invitation(session, invitation_id)
            if _to_invitation(row).status(now) is not InvitationStatus.PENDING:
                raise InvitationNotUsableError()

            await session.execute(
                insert(organization_users_association)
                .values(
                    user_id=user_id,
                    organization_id=row.organization_id,
                    role=row.role,
                    invited_by=row.invited_by,
                    created_at=now,
                )
                .on_conflict_do_nothing()
            )
            row.accepted_at = now
            row.accepted_by = user_id
            if select_organization:
                await session.execute(
                    update(UserModel)
                    .where(UserModel.id == user_id)
                    .values(selected_organization_id=row.organization_id)
                )
            await session.commit()
            await session.refresh(row)
            return _to_invitation(row)

    @staticmethod
    async def _lock_invitation(
        session: AsyncSession, invitation_id: int
    ) -> OrganizationInvitationModel:
        row = await session.scalar(
            select(_Invite).where(_Invite.id == invitation_id).with_for_update()
        )
        if row is None:
            raise InvitationNotFoundError()
        return row
