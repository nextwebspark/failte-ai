"""Data access for the platform admin area: cross-organisation lists, feature
switches, the audit log, health counts and overview numbers.

Everything here reads across organisations, so it is only called from routes
guarded by ``require_platform_admin``.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import exists, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import aliased

from api.db.base_client import BaseDBClient
from api.db.models import (
    BillingAccountModel,
    OrganizationConfigurationModel,
    OrganizationModel,
    ToolModel,
    UserModel,
    WorkflowModel,
    WorkflowRunModel,
    organization_users_association,
)
from api.db.platform_admin_models import (
    PlatformAdminAuditLogModel,
    PlatformFeatureFlagModel,
    PlatformSettingModel,
)
from api.enums import (
    OrganizationConfigurationKey,
    OrgRole,
    ToolCategory,
    ToolStatus,
    WorkflowRunMode,
    WorkflowRunState,
)
from api.errors.platform_admin import (
    LastPlatformAdminError,
    PlatformUserNotFoundError,
    SelfDemotionError,
)
from api.services.platform_admin.audit import AuditAction

_members = organization_users_association
_Flag = PlatformFeatureFlagModel
_Audit = PlatformAdminAuditLogModel
_Setting = PlatformSettingModel

# Runs that are not voice calls (text chat), left out of call counts.
TEXT_RUN_MODES = (
    WorkflowRunMode.TEXTCHAT.value,
    WorkflowRunMode.CHAT.value,
)
# ``gathered_context.call_status`` values of a call that failed: telephony
# failures and errors (TelephonyCallStatus), and pipeline errors
# (pipecat EndTaskReason).
FAILED_CALL_STATUSES = ("failed", "error", "pipeline_error", "unexpected_error")


@dataclass(frozen=True, slots=True)
class AuditEntry:
    action: str
    actor_user_id: int | None
    organization_id: int | None = None
    target_user_id: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AuditLogRow:
    id: int
    created_at: datetime
    action: str
    actor_user_id: int | None
    actor_email: str | None
    organization_id: int | None
    organization_name: str | None
    target_user_id: int | None
    target_user_email: str | None
    details: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FeatureFlagRow:
    feature: str
    organization_id: int | None
    organization_name: str | None
    enabled: bool
    updated_by: int | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AdminOrganizationRow:
    id: int
    name: str | None
    provider_id: str
    created_at: datetime | None
    erased_at: datetime | None
    deletion_scheduled_for: datetime | None
    members_count: int
    last_call_at: datetime | None
    # None when the organisation has no billing account yet.
    plan: str | None
    balance_eur: Decimal | None
    credit_limit_eur: Decimal | None
    price_per_minute_override_eur: Decimal | None
    # The stored CONCURRENT_CALL_LIMIT, or None for the default.
    concurrency_limit: int | None


@dataclass(frozen=True, slots=True)
class AdminMembership:
    organization_id: int
    organization_name: str | None
    role: OrgRole


@dataclass(frozen=True, slots=True)
class AdminUserRow:
    id: int
    email: str | None
    name: str | None
    provider_id: str
    is_platform_admin: bool
    email_verified_at: datetime | None
    created_at: datetime | None
    memberships: list[AdminMembership]


@dataclass(frozen=True, slots=True)
class AdminRunRow:
    id: int
    organization_id: int | None
    organization_name: str | None
    workflow_id: int
    workflow_name: str | None
    mode: str
    call_type: str | None
    state: str
    call_status: str | None
    duration_seconds: float | None
    created_at: datetime | None


@dataclass(frozen=True, slots=True)
class OverviewCounts:
    users_total: int
    users_new_7d: int
    users_new_30d: int
    users_new_month: int
    organizations_total: int
    organizations_new_month: int
    active_organizations_7d: int
    active_organizations_30d: int
    calls_7d: int
    calls_month: int
    minutes_month: float


# LIKE escape character for search terms (the one SQLAlchemy's autoescape uses).
_ESCAPE = "/"


def _like(term: str) -> str:
    """``%term%`` with the term's own ``%``, ``_`` and ``/`` matched literally."""
    escaped = term.replace("/", "//").replace("%", "/%").replace("_", "/_")
    return f"%{escaped}%"


def _id_term(term: str) -> int | None:
    """A search term that can be a row id (a plain positive int4), else None."""
    if term.isascii() and term.isdigit() and len(term) <= 9:
        return int(term)
    return None


def _concurrency_value(value: Any) -> int | None:
    if isinstance(value, dict) and value.get("value") is not None:
        try:
            return int(value["value"])
        except (TypeError, ValueError):
            return None
    return None


def _add_audit(session: AsyncSession, entry: AuditEntry) -> None:
    session.add(
        _Audit(
            action=entry.action,
            actor_user_id=entry.actor_user_id,
            organization_id=entry.organization_id,
            target_user_id=entry.target_user_id,
            details=entry.details,
        )
    )


def _voice_runs():
    return WorkflowRunModel.mode.notin_(TEXT_RUN_MODES)


class PlatformAdminClient(BaseDBClient):
    # -- audit log -------------------------------------------------------

    async def add_platform_audit_entry(self, entry: AuditEntry) -> None:
        async with self.async_session() as session:
            _add_audit(session, entry)
            await session.commit()

    async def list_platform_audit_entries(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        organization_id: int | None = None,
        action_prefix: str | None = None,
    ) -> tuple[list[AuditLogRow], int]:
        actor = aliased(UserModel)
        target = aliased(UserModel)
        conditions = []
        if organization_id is not None:
            conditions.append(_Audit.organization_id == organization_id)
        if action_prefix:
            conditions.append(_Audit.action.startswith(action_prefix, autoescape=True))
        async with self.async_session() as session:
            total = (
                await session.execute(
                    select(func.count()).select_from(_Audit).where(*conditions)
                )
            ).scalar_one()
            result = await session.execute(
                select(
                    _Audit,
                    actor.email.label("actor_email"),
                    OrganizationModel.name.label("organization_name"),
                    target.email.label("target_email"),
                )
                .outerjoin(actor, actor.id == _Audit.actor_user_id)
                .outerjoin(target, target.id == _Audit.target_user_id)
                .outerjoin(
                    OrganizationModel, OrganizationModel.id == _Audit.organization_id
                )
                .where(*conditions)
                .order_by(_Audit.created_at.desc(), _Audit.id.desc())
                .limit(limit)
                .offset(offset)
            )
            rows = [
                AuditLogRow(
                    id=row[0].id,
                    created_at=row[0].created_at,
                    action=row[0].action,
                    actor_user_id=row[0].actor_user_id,
                    actor_email=row.actor_email,
                    organization_id=row[0].organization_id,
                    organization_name=row.organization_name,
                    target_user_id=row[0].target_user_id,
                    target_user_email=row.target_email,
                    details=row[0].details or {},
                )
                for row in result.all()
            ]
            return rows, total

    # -- feature switches ------------------------------------------------

    async def get_feature_flag_values(
        self, organization_id: int | None
    ) -> tuple[dict[str, bool], dict[str, bool]]:
        """(platform-wide values, the organisation's overrides) as stored."""
        async with self.async_session() as session:
            conditions = [_Flag.organization_id.is_(None)]
            if organization_id is not None:
                conditions.append(_Flag.organization_id == organization_id)
            result = await session.execute(
                select(_Flag.feature, _Flag.organization_id, _Flag.enabled).where(
                    or_(*conditions)
                )
            )
            platform: dict[str, bool] = {}
            organization: dict[str, bool] = {}
            for feature, org_id, enabled in result.all():
                (platform if org_id is None else organization)[feature] = enabled
            return platform, organization

    async def features_enabled_for_some_organization(self) -> set[str]:
        async with self.async_session() as session:
            result = await session.execute(
                select(_Flag.feature)
                .where(_Flag.organization_id.is_not(None), _Flag.enabled.is_(True))
                .distinct()
            )
            return set(result.scalars().all())

    async def list_feature_flag_rows(self) -> list[FeatureFlagRow]:
        async with self.async_session() as session:
            result = await session.execute(
                select(_Flag, OrganizationModel.name)
                .outerjoin(
                    OrganizationModel, OrganizationModel.id == _Flag.organization_id
                )
                .order_by(_Flag.feature, _Flag.organization_id.nulls_first())
            )
            return [
                FeatureFlagRow(
                    feature=flag.feature,
                    organization_id=flag.organization_id,
                    organization_name=name,
                    enabled=flag.enabled,
                    updated_by=flag.updated_by,
                    updated_at=flag.updated_at,
                )
                for flag, name in result.all()
            ]

    async def set_feature_flag(
        self,
        *,
        feature: str,
        organization_id: int | None,
        enabled: bool | None,
        actor_user_id: int,
        action: str,
        _retry: bool = True,
    ) -> bool | None:
        """Store a switch (None removes it, so the default or the platform
        value applies again) and audit the change. Returns the previous
        stored value. A no-op change is not audited."""
        scope = (
            _Flag.organization_id.is_(None)
            if organization_id is None
            else _Flag.organization_id == organization_id
        )
        async with self.async_session() as session:
            row = (
                await session.execute(
                    select(_Flag)
                    .where(_Flag.feature == feature, scope)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            before = row.enabled if row is not None else None
            if before == enabled:
                return before
            if enabled is None:
                await session.delete(row)
            elif row is not None:
                row.enabled = enabled
                row.updated_by = actor_user_id
                row.updated_at = datetime.now(UTC)
            else:
                session.add(
                    _Flag(
                        feature=feature,
                        organization_id=organization_id,
                        enabled=enabled,
                        updated_by=actor_user_id,
                    )
                )
            _add_audit(
                session,
                AuditEntry(
                    action=action,
                    actor_user_id=actor_user_id,
                    organization_id=organization_id,
                    details={"feature": feature, "before": before, "after": enabled},
                ),
            )
            try:
                await session.commit()
            except IntegrityError:
                # A concurrent first write of the same switch; apply ours on
                # top of it.
                await session.rollback()
                if not _retry:
                    raise
            else:
                return before
        return await self.set_feature_flag(
            feature=feature,
            organization_id=organization_id,
            enabled=enabled,
            actor_user_id=actor_user_id,
            action=action,
            _retry=False,
        )

    # -- platform settings -----------------------------------------------

    async def get_platform_setting(self, key: str) -> dict[str, Any] | None:
        """A platform-wide value, or None when none was saved. Read by every
        member's Home, so it is not limited to platform admin routes."""
        async with self.async_session() as session:
            row = await session.get(_Setting, key)
            return row.value if row is not None else None

    async def set_platform_setting(
        self,
        *,
        key: str,
        value: dict[str, Any] | None,
        actor_user_id: int,
        action: str,
        _retry: bool = True,
    ) -> None:
        """Store a platform-wide value (None removes it, so the default in
        code applies again) and audit the change. A no-op is not audited."""
        async with self.async_session() as session:
            row = await session.get(_Setting, key, with_for_update=True)
            before = row.value if row is not None else None
            if before == value:
                return
            if value is None:
                await session.delete(row)
            elif row is not None:
                row.value = value
                row.updated_by = actor_user_id
                row.updated_at = datetime.now(UTC)
            else:
                session.add(_Setting(key=key, value=value, updated_by=actor_user_id))
            _add_audit(
                session,
                AuditEntry(
                    action=action,
                    actor_user_id=actor_user_id,
                    details={"setting": key, "before": before, "after": value},
                ),
            )
            try:
                await session.commit()
            except IntegrityError:
                # A concurrent first save of the same key: apply ours on top.
                await session.rollback()
                if not _retry:
                    raise
            else:
                return
        await self.set_platform_setting(
            key=key,
            value=value,
            actor_user_id=actor_user_id,
            action=action,
            _retry=False,
        )

    # -- organisations ---------------------------------------------------

    def _organization_columns(self):
        members_count = (
            select(func.count())
            .select_from(_members)
            .where(_members.c.organization_id == OrganizationModel.id)
            .correlate(OrganizationModel)
            .scalar_subquery()
        )
        last_call_at = (
            select(func.max(WorkflowRunModel.created_at))
            .join(WorkflowModel, WorkflowModel.id == WorkflowRunModel.workflow_id)
            .where(WorkflowModel.organization_id == OrganizationModel.id)
            .correlate(OrganizationModel)
            .scalar_subquery()
        )
        return select(
            OrganizationModel.id,
            OrganizationModel.name,
            OrganizationModel.provider_id,
            OrganizationModel.created_at,
            OrganizationModel.erased_at,
            OrganizationModel.deletion_scheduled_for,
            members_count.label("members_count"),
            last_call_at.label("last_call_at"),
            BillingAccountModel.plan,
            BillingAccountModel.balance_eur,
            BillingAccountModel.credit_limit_eur,
            BillingAccountModel.price_per_minute_eur,
        ).outerjoin(
            BillingAccountModel,
            BillingAccountModel.organization_id == OrganizationModel.id,
        )

    async def _concurrency_limits(
        self, session: AsyncSession, organization_ids: list[int]
    ) -> dict[int, int | None]:
        if not organization_ids:
            return {}
        # The value column is encrypted, so it is read here, not in SQL.
        result = await session.execute(
            select(OrganizationConfigurationModel).where(
                OrganizationConfigurationModel.organization_id.in_(organization_ids),
                OrganizationConfigurationModel.key
                == OrganizationConfigurationKey.CONCURRENT_CALL_LIMIT.value,
            )
        )
        return {
            config.organization_id: _concurrency_value(config.value)
            for config in result.scalars().all()
        }

    @staticmethod
    def _to_organization_row(row, limits: dict[int, int | None]):
        return AdminOrganizationRow(
            id=row.id,
            name=row.name,
            provider_id=row.provider_id,
            created_at=row.created_at,
            erased_at=row.erased_at,
            deletion_scheduled_for=row.deletion_scheduled_for,
            members_count=row.members_count or 0,
            last_call_at=row.last_call_at,
            plan=row.plan,
            balance_eur=row.balance_eur,
            credit_limit_eur=row.credit_limit_eur,
            price_per_minute_override_eur=row.price_per_minute_eur,
            concurrency_limit=limits.get(row.id),
        )

    async def list_admin_organizations(
        self, *, search: str | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[AdminOrganizationRow], int]:
        """Every organisation, newest first. ``search`` matches the name, the
        id, or a member's email."""
        conditions = []
        term = (search or "").strip()
        if term:
            pattern = _like(term)
            member_email = exists().where(
                _members.c.organization_id == OrganizationModel.id,
                _members.c.user_id == UserModel.id,
                UserModel.email.ilike(pattern, escape=_ESCAPE),
            )
            matches = [
                OrganizationModel.name.ilike(pattern, escape=_ESCAPE),
                member_email,
            ]
            if (term_id := _id_term(term)) is not None:
                matches.append(OrganizationModel.id == term_id)
            conditions.append(or_(*matches))
        async with self.async_session() as session:
            total = (
                await session.execute(
                    select(func.count())
                    .select_from(OrganizationModel)
                    .where(*conditions)
                )
            ).scalar_one()
            result = await session.execute(
                self._organization_columns()
                .where(*conditions)
                .order_by(
                    OrganizationModel.created_at.desc().nulls_last(),
                    OrganizationModel.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
            rows = result.all()
            limits = await self._concurrency_limits(session, [r.id for r in rows])
            return [self._to_organization_row(r, limits) for r in rows], total

    async def get_admin_organization(
        self, organization_id: int
    ) -> AdminOrganizationRow | None:
        async with self.async_session() as session:
            row = (
                await session.execute(
                    self._organization_columns().where(
                        OrganizationModel.id == organization_id
                    )
                )
            ).first()
            if row is None:
                return None
            limits = await self._concurrency_limits(session, [organization_id])
            return self._to_organization_row(row, limits)

    async def set_organization_concurrency_limit(
        self,
        *,
        organization_id: int,
        limit: int | None,
        actor_user_id: int,
        _retry: bool = True,
    ) -> int | None:
        """Store the organisation's concurrent-call limit (None goes back to
        the platform default) and audit it. Returns the previous value."""
        key = OrganizationConfigurationKey.CONCURRENT_CALL_LIMIT.value
        async with self.async_session() as session:
            config = (
                await session.execute(
                    select(OrganizationConfigurationModel)
                    .where(
                        OrganizationConfigurationModel.organization_id
                        == organization_id,
                        OrganizationConfigurationModel.key == key,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            before = _concurrency_value(config.value) if config else None
            if before == limit:
                return before
            now = datetime.now(UTC)
            if limit is None:
                await session.delete(config)
            elif config is not None:
                config.value = {"value": limit}
                config.updated_at = now
            else:
                session.add(
                    OrganizationConfigurationModel(
                        organization_id=organization_id,
                        key=key,
                        value={"value": limit},
                        updated_at=now,
                    )
                )
            _add_audit(
                session,
                AuditEntry(
                    action=AuditAction.CONCURRENCY_LIMIT_SET,
                    actor_user_id=actor_user_id,
                    organization_id=organization_id,
                    details={"before": before, "after": limit},
                ),
            )
            try:
                await session.commit()
            except IntegrityError:
                # A concurrent first write of the limit; apply ours on top.
                await session.rollback()
                if not _retry:
                    raise
            else:
                return before
        return await self.set_organization_concurrency_limit(
            organization_id=organization_id,
            limit=limit,
            actor_user_id=actor_user_id,
            _retry=False,
        )

    async def list_admin_runs(
        self,
        *,
        organization_id: int | None = None,
        limit: int = 20,
        conditions: list | None = None,
    ) -> list[AdminRunRow]:
        where = list(conditions or [])
        if organization_id is not None:
            where.append(WorkflowModel.organization_id == organization_id)
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    WorkflowRunModel.id,
                    WorkflowModel.organization_id,
                    OrganizationModel.name.label("organization_name"),
                    WorkflowRunModel.workflow_id,
                    WorkflowModel.name.label("workflow_name"),
                    WorkflowRunModel.mode,
                    WorkflowRunModel.call_type,
                    WorkflowRunModel.state,
                    WorkflowRunModel.gathered_context["call_status"]
                    .as_string()
                    .label("call_status"),
                    WorkflowRunModel.usage_info["call_duration_seconds"]
                    .as_float()
                    .label("duration_seconds"),
                    WorkflowRunModel.created_at,
                )
                .join(WorkflowModel, WorkflowModel.id == WorkflowRunModel.workflow_id)
                .outerjoin(
                    OrganizationModel,
                    OrganizationModel.id == WorkflowModel.organization_id,
                )
                .where(*where)
                .order_by(
                    WorkflowRunModel.created_at.desc(), WorkflowRunModel.id.desc()
                )
                .limit(limit)
            )
            return [
                AdminRunRow(
                    id=row.id,
                    organization_id=row.organization_id,
                    organization_name=row.organization_name,
                    workflow_id=row.workflow_id,
                    workflow_name=row.workflow_name,
                    mode=row.mode,
                    call_type=row.call_type,
                    state=row.state,
                    call_status=row.call_status,
                    duration_seconds=row.duration_seconds,
                    created_at=row.created_at,
                )
                for row in result.all()
            ]

    # -- users -----------------------------------------------------------

    async def list_admin_users(
        self,
        *,
        search: str | None = None,
        platform_admins_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AdminUserRow], int]:
        conditions = []
        term = (search or "").strip()
        if term:
            pattern = _like(term)
            matches = [
                UserModel.email.ilike(pattern, escape=_ESCAPE),
                UserModel.name.ilike(pattern, escape=_ESCAPE),
            ]
            if (term_id := _id_term(term)) is not None:
                matches.append(UserModel.id == term_id)
            conditions.append(or_(*matches))
        if platform_admins_only:
            conditions.append(UserModel.is_superuser.is_(True))
        async with self.async_session() as session:
            total = (
                await session.execute(
                    select(func.count()).select_from(UserModel).where(*conditions)
                )
            ).scalar_one()
            users = (
                await session.execute(
                    select(
                        UserModel.id,
                        UserModel.email,
                        UserModel.name,
                        UserModel.provider_id,
                        UserModel.is_superuser,
                        UserModel.email_verified_at,
                        UserModel.created_at,
                    )
                    .where(*conditions)
                    .order_by(
                        UserModel.created_at.desc().nulls_last(), UserModel.id.desc()
                    )
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            memberships: dict[int, list[AdminMembership]] = {u.id: [] for u in users}
            if users:
                result = await session.execute(
                    select(
                        _members.c.user_id,
                        OrganizationModel.id,
                        OrganizationModel.name,
                        _members.c.role,
                    )
                    .join(
                        OrganizationModel,
                        OrganizationModel.id == _members.c.organization_id,
                    )
                    .where(_members.c.user_id.in_(list(memberships)))
                    .order_by(OrganizationModel.id)
                )
                for user_id, org_id, org_name, role in result.all():
                    memberships[user_id].append(
                        AdminMembership(org_id, org_name, OrgRole(role))
                    )
            return [
                AdminUserRow(
                    id=u.id,
                    email=u.email,
                    name=u.name,
                    provider_id=u.provider_id,
                    is_platform_admin=bool(u.is_superuser),
                    email_verified_at=u.email_verified_at,
                    created_at=u.created_at,
                    memberships=memberships[u.id],
                )
                for u in users
            ], total

    async def list_admin_organization_members(
        self, organization_id: int
    ) -> list[dict[str, Any]]:
        async with self.async_session() as session:
            result = await session.execute(
                select(
                    UserModel.id,
                    UserModel.email,
                    UserModel.name,
                    UserModel.is_superuser,
                    UserModel.email_verified_at,
                    _members.c.role,
                    _members.c.created_at,
                )
                .join(_members, _members.c.user_id == UserModel.id)
                .where(_members.c.organization_id == organization_id)
                .order_by(_members.c.created_at, UserModel.id)
            )
            return [
                {
                    "user_id": row.id,
                    "email": row.email,
                    "name": row.name,
                    "is_platform_admin": bool(row.is_superuser),
                    "email_verified": row.email_verified_at is not None,
                    "role": OrgRole(row.role),
                    "joined_at": row.created_at,
                }
                for row in result.all()
            ]

    async def set_platform_admin(
        self, *, target_user_id: int, is_platform_admin: bool, actor_user_id: int
    ) -> bool:
        """Grant or revoke platform admin. Refuses self-demotion and removing
        the last platform admin. Returns whether anything changed."""
        async with self.async_session() as session:
            # Lock every admin row first, so two concurrent revokes cannot
            # each see the other as the remaining admin.
            admin_ids = (
                (
                    await session.execute(
                        select(UserModel.id)
                        .where(UserModel.is_superuser.is_(True))
                        .order_by(UserModel.id)
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
            target = (
                await session.execute(
                    select(UserModel)
                    .where(UserModel.id == target_user_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if target is None:
                raise PlatformUserNotFoundError()
            if bool(target.is_superuser) == is_platform_admin:
                return False
            if not is_platform_admin:
                if target_user_id == actor_user_id:
                    raise SelfDemotionError()
                if len([i for i in admin_ids if i != target_user_id]) == 0:
                    raise LastPlatformAdminError()
            target.is_superuser = is_platform_admin
            _add_audit(
                session,
                AuditEntry(
                    action=(
                        AuditAction.PLATFORM_ADMIN_GRANTED
                        if is_platform_admin
                        else AuditAction.PLATFORM_ADMIN_REVOKED
                    ),
                    actor_user_id=actor_user_id,
                    target_user_id=target_user_id,
                ),
            )
            await session.commit()
            return True

    # -- health ----------------------------------------------------------

    async def count_failed_runs(self, *, since: datetime) -> int:
        status = WorkflowRunModel.gathered_context["call_status"].as_string()
        async with self.async_session() as session:
            return (
                await session.execute(
                    select(func.count())
                    .select_from(WorkflowRunModel)
                    .where(
                        WorkflowRunModel.created_at >= since,
                        status.in_(FAILED_CALL_STATUSES),
                    )
                )
            ).scalar_one()

    async def stuck_runs(
        self, *, since: datetime, started_before: datetime, limit: int = 20
    ) -> tuple[int, list[AdminRunRow]]:
        """Runs created since ``since`` but before ``started_before`` that are
        still initialized or running."""
        conditions = [
            WorkflowRunModel.created_at >= since,
            WorkflowRunModel.created_at < started_before,
            WorkflowRunModel.state.in_(
                [WorkflowRunState.INITIALIZED.value, WorkflowRunState.RUNNING.value]
            ),
        ]
        async with self.async_session() as session:
            total = (
                await session.execute(
                    select(func.count())
                    .select_from(WorkflowRunModel)
                    .where(*conditions)
                )
            ).scalar_one()
        sample = await self.list_admin_runs(limit=limit, conditions=conditions)
        return total, sample

    async def organizations_with_integration_tools(self) -> list[int]:
        """Organisations with an installed catalog integration (a tools
        service connection), for the connection health check."""
        async with self.async_session() as session:
            result = await session.execute(
                select(ToolModel.organization_id)
                .where(
                    ToolModel.category == ToolCategory.INTEGRATION.value,
                    ToolModel.status != ToolStatus.ARCHIVED.value,
                )
                .distinct()
                .order_by(ToolModel.organization_id)
            )
            return list(result.scalars().all())

    # -- overview --------------------------------------------------------

    async def platform_overview_counts(
        self,
        *,
        month_start: datetime,
        since_7d: datetime,
        since_30d: datetime,
    ) -> OverviewCounts:
        def count_users(since: datetime | None):
            query = select(func.count()).select_from(UserModel)
            if since is not None:
                query = query.where(UserModel.created_at >= since)
            return query

        def active_organizations(since: datetime):
            organizations = (
                select(WorkflowModel.organization_id)
                .join(
                    WorkflowRunModel, WorkflowRunModel.workflow_id == WorkflowModel.id
                )
                .where(
                    WorkflowRunModel.created_at >= since,
                    WorkflowModel.organization_id.is_not(None),
                    _voice_runs(),
                )
                .distinct()
                .subquery()
            )
            return select(func.count()).select_from(organizations)

        def voice_runs_since(since: datetime):
            return (
                select(func.count())
                .select_from(WorkflowRunModel)
                .where(WorkflowRunModel.created_at >= since, _voice_runs())
            )

        live_orgs = OrganizationModel.erased_at.is_(None)
        duration = WorkflowRunModel.usage_info["call_duration_seconds"].as_float()
        async with self.async_session() as session:

            async def scalar(query) -> Any:
                return (await session.execute(query)).scalar_one()

            return OverviewCounts(
                users_total=await scalar(count_users(None)),
                users_new_7d=await scalar(count_users(since_7d)),
                users_new_30d=await scalar(count_users(since_30d)),
                users_new_month=await scalar(count_users(month_start)),
                organizations_total=await scalar(
                    select(func.count()).select_from(OrganizationModel).where(live_orgs)
                ),
                organizations_new_month=await scalar(
                    select(func.count())
                    .select_from(OrganizationModel)
                    .where(live_orgs, OrganizationModel.created_at >= month_start)
                ),
                active_organizations_7d=await scalar(active_organizations(since_7d)),
                active_organizations_30d=await scalar(active_organizations(since_30d)),
                calls_7d=await scalar(voice_runs_since(since_7d)),
                calls_month=await scalar(voice_runs_since(month_start)),
                minutes_month=float(
                    await scalar(
                        select(func.coalesce(func.sum(duration), 0.0)).where(
                            WorkflowRunModel.created_at >= month_start, _voice_runs()
                        )
                    )
                )
                / 60.0,
            )


__all__ = [
    "AdminMembership",
    "AdminOrganizationRow",
    "AdminRunRow",
    "AdminUserRow",
    "AuditEntry",
    "AuditLogRow",
    "FeatureFlagRow",
    "OverviewCounts",
    "PlatformAdminClient",
]
