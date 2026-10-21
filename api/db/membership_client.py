"""Data access for organization memberships (``organization_users``)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, delete, func, update
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
from api.errors.privacy import (
    LastAdminWithMembersError,
    PrivacyError,
    SoleMemberOfOrganizationError,
)

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
            await self._lock_organization(session, organization_id)
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
            await self._lock_organization(session, organization_id)
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

    # -- account deletion ---------------------------------------------------

    async def check_user_account_deletable(self, user_id: int) -> None:
        """Raise the reason the user's account cannot be deleted, if any.

        See :meth:`delete_user_account`; this is the same check without
        deleting, for callers that must act elsewhere (an identity provider)
        before the account goes.
        """
        async with self.async_session() as session:
            blocker = await self._account_deletion_blocker(session, user_id)
            if blocker is not None:
                raise blocker

    async def delete_user_account(
        self,
        user_id: int,
        *,
        before_commit: Callable[[], Awaitable[None]] | None = None,
    ) -> bool:
        """Delete a user and their memberships; keep what they created.

        Refuses, raising a ``PrivacyError``, when the user is the only admin of
        an organisation that has other members, or the only member of one that
        is not already scheduled for deletion. The user's API keys are
        archived; their configurations, tokens and memberships go with the
        user row, and everything they created stays with its organisation with
        the creator cleared. Returns False if there was no such user.

        ``before_commit`` runs after the check and the deletes, under the
        organization locks, before the commit (e.g. deleting the user at the
        identity provider): if it raises, nothing is deleted.
        """
        async with self.async_session() as session:
            organization_ids = (
                (
                    await session.execute(
                        select(_members.c.organization_id)
                        .where(_members.c.user_id == user_id)
                        .order_by(_members.c.organization_id)
                    )
                )
                .scalars()
                .all()
            )
            # Same lock order as role changes and removals (organization
            # first), so the last-admin check sees a stable set of admins.
            for organization_id in organization_ids:
                await self._lock_organization(session, organization_id)
            blocker = await self._account_deletion_blocker(session, user_id)
            if blocker is not None:
                raise blocker

            # A savepoint, so a failing ``before_commit`` undoes the deletes
            # while the organization locks are still held.
            savepoint = await session.begin_nested()
            try:
                await session.execute(
                    update(APIKeyModel)
                    .where(
                        APIKeyModel.created_by == user_id,
                        APIKeyModel.archived_at.is_(None),
                    )
                    .values(is_active=False, archived_at=datetime.now(UTC))
                )
                await session.execute(
                    _members.delete().where(_members.c.user_id == user_id)
                )
                result = await session.execute(
                    delete(UserModel).where(UserModel.id == user_id)
                )
                if before_commit is not None:
                    await before_commit()
            except BaseException:
                await savepoint.rollback()
                raise
            await savepoint.commit()
            await session.commit()
            return bool(result.rowcount)

    @staticmethod
    async def _account_deletion_blocker(
        session: AsyncSession, user_id: int
    ) -> PrivacyError | None:
        memberships = await session.execute(
            select(
                OrganizationModel.id,
                OrganizationModel.name,
                _members.c.role,
                OrganizationModel.deletion_requested_at.is_not(None).label(
                    "pending_deletion"
                ),
            )
            .join(_members, _members.c.organization_id == OrganizationModel.id)
            .where(
                _members.c.user_id == user_id,
                OrganizationModel.erased_at.is_(None),
            )
            .order_by(OrganizationModel.id)
        )
        for organization_id, name, role, pending_deletion in memberships.all():
            others = await session.execute(
                select(_members.c.role).where(
                    _members.c.organization_id == organization_id,
                    _members.c.user_id != user_id,
                )
            )
            other_roles = list(others.scalars().all())
            if not other_roles:
                # Its own deletion is already scheduled: nothing is orphaned.
                if pending_deletion:
                    continue
                return SoleMemberOfOrganizationError(organization_id, name)
            if role == OrgRole.ADMIN.value and OrgRole.ADMIN.value not in other_roles:
                return LastAdminWithMembersError(organization_id, name)
        return None

    async def update_organization_name(self, organization_id: int, name: str) -> None:
        async with self.async_session() as session:
            await session.execute(
                update(OrganizationModel)
                .where(OrganizationModel.id == organization_id)
                .values(name=name)
            )
            await session.commit()

    @staticmethod
    async def _lock_organization(session: AsyncSession, organization_id: int) -> None:
        """Serialize membership changes per organization.

        Every role change and removal takes this lock first, so concurrent
        changes never acquire membership row locks in opposite orders
        (deadlock) and the last-admin check sees a stable set of admins.
        """
        await session.execute(
            select(OrganizationModel.id)
            .where(OrganizationModel.id == organization_id)
            .with_for_update()
        )

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
        # Callers hold the organization lock, so this set of admins cannot
        # change underneath the check.
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
