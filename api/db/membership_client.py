"""Data access for organization memberships (``organization_users``)."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from api.db.base_client import BaseDBClient
from api.db.models import (
    APIKeyModel,
    OrganizationModel,
    UserModel,
    organization_users_association,
)
from api.enums import OrgRole
from api.errors.membership import LastAdminError, MemberNotFoundError

_members = organization_users_association


@dataclass(frozen=True, slots=True)
class OrganizationMember:
    """A user as seen from one organization's member list."""

    user_id: int
    email: str | None
    name: str | None
    role: OrgRole
    joined_at: datetime | None
    invited_by: int | None


@dataclass(frozen=True, slots=True)
class UserOrganization:
    """An organization as seen from one user's membership list."""

    organization_id: int
    name: str | None
    provider_id: str
    role: OrgRole


@dataclass(frozen=True, slots=True)
class UserIdentity:
    user_id: int
    email: str | None
    name: str | None


@dataclass(frozen=True, slots=True)
class OrganizationSummary:
    organization_id: int
    name: str | None
    provider_id: str


class MembershipClient(BaseDBClient):
    async def get_user_identity(self, user_id: int) -> UserIdentity | None:
        async with self.async_session() as session:
            row = (
                await session.execute(
                    select(UserModel.id, UserModel.email, UserModel.name).where(
                        UserModel.id == user_id
                    )
                )
            ).first()
            return UserIdentity(row.id, row.email, row.name) if row else None

    async def get_user_identity_by_email(self, email: str) -> UserIdentity | None:
        async with self.async_session() as session:
            row = (
                await session.execute(
                    select(UserModel.id, UserModel.email, UserModel.name).where(
                        func.lower(UserModel.email) == email.lower()
                    )
                )
            ).first()
            return UserIdentity(row.id, row.email, row.name) if row else None

    async def get_organization_summary(
        self, organization_id: int
    ) -> OrganizationSummary | None:
        async with self.async_session() as session:
            row = (
                await session.execute(
                    select(
                        OrganizationModel.id,
                        OrganizationModel.name,
                        OrganizationModel.provider_id,
                    ).where(OrganizationModel.id == organization_id)
                )
            ).first()
            return (
                OrganizationSummary(row.id, row.name, row.provider_id) if row else None
            )

    async def get_member_role(
        self, user_id: int, organization_id: int
    ) -> OrgRole | None:
        """Return the user's role in the organization, or None if not a member."""
        async with self.async_session() as session:
            result = await session.execute(
                select(_members.c.role).where(
                    _members.c.user_id == user_id,
                    _members.c.organization_id == organization_id,
                )
            )
            role = result.scalar_one_or_none()
            return OrgRole(role) if role is not None else None

    async def list_organization_members(
        self, organization_id: int
    ) -> list[OrganizationMember]:
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    UserModel.id,
                    UserModel.email,
                    UserModel.name,
                    _members.c.role,
                    _members.c.created_at,
                    _members.c.invited_by,
                )
                .join(_members, _members.c.user_id == UserModel.id)
                .where(_members.c.organization_id == organization_id)
                .order_by(_members.c.created_at, UserModel.id)
            )
            return [
                OrganizationMember(
                    user_id=row.id,
                    email=row.email,
                    name=row.name,
                    role=OrgRole(row.role),
                    joined_at=row.created_at,
                    invited_by=row.invited_by,
                )
                for row in result.all()
            ]

    async def list_user_organizations(self, user_id: int) -> list[UserOrganization]:
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    OrganizationModel.id,
                    OrganizationModel.name,
                    OrganizationModel.provider_id,
                    _members.c.role,
                )
                .join(_members, _members.c.organization_id == OrganizationModel.id)
                .where(_members.c.user_id == user_id)
                .order_by(OrganizationModel.id)
            )
            return [
                UserOrganization(
                    organization_id=row.id,
                    name=row.name,
                    provider_id=row.provider_id,
                    role=OrgRole(row.role),
                )
                for row in result.all()
            ]

    async def update_member_role(
        self, organization_id: int, user_id: int, role: OrgRole
    ) -> None:
        """Change a member's role.

        Raises:
            MemberNotFoundError: the user is not a member of the organization.
            LastAdminError: the change would demote the only admin.
        """
        async with self.async_session() as session:
            current = await self._lock_member_role(session, organization_id, user_id)
            if current == role:
                return
            if current == OrgRole.ADMIN:
                await self._ensure_another_admin(session, organization_id, user_id)
            await session.execute(
                update(_members)
                .where(
                    _members.c.organization_id == organization_id,
                    _members.c.user_id == user_id,
                )
                .values(role=role.value)
            )
            await session.commit()

    async def remove_organization_member(
        self, organization_id: int, user_id: int
    ) -> None:
        """Remove a member, archive their API keys in the org, and clear their
        selected organization if it pointed here.

        Raises:
            MemberNotFoundError: the user is not a member of the organization.
            LastAdminError: the member is the only admin.
        """
        async with self.async_session() as session:
            current = await self._lock_member_role(session, organization_id, user_id)
            if current == OrgRole.ADMIN:
                await self._ensure_another_admin(session, organization_id, user_id)

            await session.execute(
                _members.delete().where(
                    _members.c.organization_id == organization_id,
                    _members.c.user_id == user_id,
                )
            )
            await session.execute(
                update(APIKeyModel)
                .where(
                    APIKeyModel.organization_id == organization_id,
                    APIKeyModel.created_by == user_id,
                    APIKeyModel.archived_at.is_(None),
                )
                .values(is_active=False, archived_at=datetime.now(UTC))
            )
            await session.execute(
                update(UserModel)
                .where(
                    and_(
                        UserModel.id == user_id,
                        UserModel.selected_organization_id == organization_id,
                    )
                )
                .values(selected_organization_id=None)
            )
            await session.commit()

    async def update_organization_name(self, organization_id: int, name: str) -> None:
        async with self.async_session() as session:
            await session.execute(
                update(OrganizationModel)
                .where(OrganizationModel.id == organization_id)
                .values(name=name)
            )
            await session.commit()

    @staticmethod
    async def _lock_member_role(
        session: AsyncSession, organization_id: int, user_id: int
    ) -> OrgRole:
        result = await session.execute(
            select(_members.c.role)
            .where(
                _members.c.organization_id == organization_id,
                _members.c.user_id == user_id,
            )
            .with_for_update()
        )
        role = result.scalar_one_or_none()
        if role is None:
            raise MemberNotFoundError()
        return OrgRole(role)

    @staticmethod
    async def _ensure_another_admin(
        session: AsyncSession, organization_id: int, excluding_user_id: int
    ) -> None:
        # Lock every admin row so two concurrent demotions cannot both see the
        # other admin and leave the organization with none.
        admins = await session.execute(
            select(_members.c.user_id)
            .where(
                _members.c.organization_id == organization_id,
                _members.c.role == OrgRole.ADMIN.value,
            )
            .with_for_update()
        )
        others = [uid for uid in admins.scalars().all() if uid != excluding_user_id]
        if not others:
            raise LastAdminError()
