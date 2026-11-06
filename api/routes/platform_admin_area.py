"""The founders' platform admin area: overview numbers, health, feature
switches, organisations, users and the audit log.

Every route needs ``require_platform_admin`` (``users.is_superuser``). Billing
changes go through ``/superuser/billing`` (api/routes/billing_admin.py);
impersonation through ``/superuser/impersonate``. Each change is written to
``platform_admin_audit_log``: in the same transaction for the changes made
here (feature switches, concurrency limits, admin grants); just after the
change for billing and impersonation, whose writes live elsewhere.

Hidden from the OpenAPI schema like the other superuser billing routes: these
are internal tools, not part of the published API.
"""

import os
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from api import constants
from api.db import db_client
from api.db.billing_client import BillingLedgerEntry
from api.db.models import UserModel
from api.db.platform_admin_client import AdminOrganizationRow, AdminRunRow
from api.enums import BillingPlan
from api.routes.superuser import IMPERSONATION_UNAVAILABLE_LOCAL
from api.schemas.platform_admin import (
    AdminAuditEntry,
    AdminAuditLogResponse,
    AdminFeature,
    AdminFeaturesResponse,
    AdminHealthResponse,
    AdminLedgerEntry,
    AdminOrganization,
    AdminOrganizationDetailResponse,
    AdminOrganizationListResponse,
    AdminOrganizationMember,
    AdminOverviewResponse,
    AdminRun,
    AdminUser,
    AdminUserListResponse,
    AdminUserMembership,
    ConcurrencyLimitResponse,
    FeatureOrganizationOverride,
    HealthCheck,
    HealthConnectionProblem,
    HealthConnections,
    OverviewRevenue,
    SetConcurrencyLimitRequest,
    SetFeatureRequest,
    SetPlatformAdminRequest,
    SetPlatformAdminResponse,
)
from api.services.auth.platform_admin import require_platform_admin
from api.services.billing.margins import monthly_margins
from api.services.billing.pricing import price_per_minute_eur
from api.services.platform_admin import features
from api.services.platform_admin.audit import AuditAction
from api.services.platform_admin.health import (
    config_checks,
    scan_integration_connections,
    settings_from_environment,
)

router = APIRouter(prefix="/superuser/admin", tags=["superuser"])

PlatformAdmin = Annotated[UserModel, Depends(require_platform_admin)]
Page = Annotated[int, Query(ge=1)]
Limit = Annotated[int, Query(ge=1, le=100)]


def _default_concurrency_limit() -> int:
    return int(constants.DEFAULT_ORG_CONCURRENCY_LIMIT)


def _organization(row: AdminOrganizationRow) -> AdminOrganization:
    plan = BillingPlan(row.plan) if row.plan else None
    if row.erased_at is not None:
        status = "erased"
    elif row.deletion_scheduled_for is not None:
        status = "deletion_scheduled"
    else:
        status = "active"
    return AdminOrganization(
        id=row.id,
        name=row.name,
        created_at=row.created_at,
        status=status,
        members_count=row.members_count,
        last_call_at=row.last_call_at,
        plan=plan,
        balance_eur=row.balance_eur,
        credit_limit_eur=row.credit_limit_eur,
        price_per_minute_override_eur=row.price_per_minute_override_eur,
        effective_price_per_minute_eur=price_per_minute_eur(
            plan or BillingPlan.PAYG, row.price_per_minute_override_eur
        ),
        concurrency_limit=row.concurrency_limit,
        effective_concurrency_limit=(
            row.concurrency_limit
            if row.concurrency_limit is not None
            else _default_concurrency_limit()
        ),
    )


def _run(row: AdminRunRow) -> AdminRun:
    return AdminRun(
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


def _ledger_entry(entry: BillingLedgerEntry) -> AdminLedgerEntry:
    return AdminLedgerEntry(
        id=entry.id,
        entry_type=entry.entry_type.value,
        amount_eur=entry.amount_eur,
        balance_after_eur=entry.balance_after_eur,
        description=entry.description,
        workflow_run_id=entry.workflow_run_id,
        created_by=entry.created_by,
        created_at=entry.created_at,
    )


async def _require_organization(organization_id: int) -> None:
    if await db_client.get_organization_by_id(organization_id) is None:
        raise HTTPException(status_code=404, detail="Organization not found")


def _require_feature(key: str) -> str:
    if key not in features.FEATURES:
        raise HTTPException(status_code=404, detail="Unknown feature")
    return key


# -- overview ---------------------------------------------------------------


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _revenue(month: str) -> OverviewRevenue:
    if constants.BILLING_PROVIDER != "stripe":
        return OverviewRevenue(
            month=month,
            available=False,
            note=(
                f"BILLING_PROVIDER is {constants.BILLING_PROVIDER}: calls are not "
                "charged in this app, so there is no revenue to show."
            ),
        )
    margins = await monthly_margins(month)
    revenue = sum((m.revenue_eur for m in margins), Decimal(0))
    costed = sum((m.costed_revenue_eur for m in margins), Decimal(0))
    cost = sum((m.provider_cost_eur for m in margins), Decimal(0))
    margin = costed - cost
    return OverviewRevenue(
        month=month,
        available=True,
        note=(
            "Margin compares only the calls whose provider cost could be "
            "estimated; provider costs are estimates."
        ),
        revenue_eur=revenue,
        provider_cost_eur=cost,
        margin_eur=margin,
        margin_percent=(
            (margin / costed * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            if costed > 0
            else None
        ),
        charged_calls=sum(m.calls for m in margins),
        uncosted_calls=sum(m.uncosted_calls for m in margins),
    )


@router.get("/overview", response_model=AdminOverviewResponse, include_in_schema=False)
async def get_overview(_admin: PlatformAdmin) -> AdminOverviewResponse:
    now = datetime.now(UTC)
    month_start = _month_start(now)
    counts = await db_client.platform_overview_counts(
        month_start=month_start,
        since_7d=now - timedelta(days=7),
        since_30d=now - timedelta(days=30),
    )
    return AdminOverviewResponse(
        generated_at=now,
        users_total=counts.users_total,
        users_new_7d=counts.users_new_7d,
        users_new_30d=counts.users_new_30d,
        users_new_month=counts.users_new_month,
        organizations_total=counts.organizations_total,
        organizations_new_month=counts.organizations_new_month,
        active_organizations_7d=counts.active_organizations_7d,
        active_organizations_30d=counts.active_organizations_30d,
        calls_7d=counts.calls_7d,
        calls_month=counts.calls_month,
        minutes_month=round(counts.minutes_month, 1),
        revenue=await _revenue(month_start.strftime("%Y-%m")),
    )


# -- health -------------------------------------------------------------------


@router.get("/health", response_model=AdminHealthResponse, include_in_schema=False)
async def get_health(_admin: PlatformAdmin) -> AdminHealthResponse:
    now = datetime.now(UTC)
    since = now - timedelta(hours=24)
    failed = await db_client.count_failed_runs(since=since)
    stuck_total, stuck_sample = await db_client.stuck_runs(
        since=since, started_before=now - timedelta(hours=1)
    )
    scan = await scan_integration_connections(
        await db_client.organizations_with_integration_tools(),
        tools_service_url=constants.TOOLS_SERVICE_URL,
        tools_internal_secret=constants.TOOLS_INTERNAL_SECRET,
    )
    names: dict[int, str | None] = {}
    for problem in scan.problems:
        if problem.organization_id not in names:
            org = await db_client.get_organization_by_id(problem.organization_id)
            names[problem.organization_id] = org.name if org else None
    return AdminHealthResponse(
        generated_at=now,
        checks=[
            HealthCheck(
                id=check.id,
                label=check.label,
                status=check.status.value,
                detail=check.detail,
            )
            for check in config_checks(settings_from_environment(os.environ))
        ],
        failed_calls_24h=failed,
        stuck_runs_24h=stuck_total,
        stuck_runs=[_run(row) for row in stuck_sample],
        connections=HealthConnections(
            checked=scan.checked,
            organizations_checked=scan.organizations_checked,
            problems=[
                HealthConnectionProblem(
                    organization_id=p.organization_id,
                    organization_name=names.get(p.organization_id),
                    connection_id=p.connection_id,
                    provider=p.provider,
                    account_label=p.account_label,
                    last_error=p.last_error,
                    error_code=p.error_code,
                )
                for p in scan.problems
            ],
            note=scan.note,
        ),
    )


# -- feature switches -------------------------------------------------------


@router.get("/features", response_model=AdminFeaturesResponse, include_in_schema=False)
async def list_features(_admin: PlatformAdmin) -> AdminFeaturesResponse:
    rows = await db_client.list_feature_flag_rows()
    platform = {r.feature: r.enabled for r in rows if r.organization_id is None}
    effective = features.platform_values(platform)
    return AdminFeaturesResponse(
        features=[
            AdminFeature(
                key=definition.key,
                label=definition.label,
                description=definition.description,
                default=definition.default,
                platform_value=platform.get(definition.key),
                effective_platform_value=effective[definition.key],
                overrides=[
                    FeatureOrganizationOverride(
                        organization_id=r.organization_id,
                        organization_name=r.organization_name,
                        enabled=r.enabled,
                        updated_at=r.updated_at,
                    )
                    for r in rows
                    if r.feature == definition.key and r.organization_id is not None
                ],
            )
            for definition in features.FEATURES.values()
        ]
    )


@router.put(
    "/features/{feature}", response_model=AdminFeaturesResponse, include_in_schema=False
)
async def set_platform_feature(
    feature: str, body: SetFeatureRequest, admin: PlatformAdmin
) -> AdminFeaturesResponse:
    """Switch a feature on or off for every organisation without an override
    (``enabled: null`` goes back to the default in code)."""
    await db_client.set_feature_flag(
        feature=_require_feature(feature),
        organization_id=None,
        enabled=body.enabled,
        actor_user_id=admin.id,
        action=AuditAction.FEATURE_PLATFORM_SET,
    )
    return await list_features(admin)


@router.put(
    "/features/{feature}/organizations/{organization_id}",
    response_model=AdminFeaturesResponse,
    include_in_schema=False,
)
async def set_organization_feature(
    feature: str,
    organization_id: int,
    body: SetFeatureRequest,
    admin: PlatformAdmin,
) -> AdminFeaturesResponse:
    """Override a feature for one organisation (``enabled: null`` removes the
    override)."""
    key = _require_feature(feature)
    await _require_organization(organization_id)
    await db_client.set_feature_flag(
        feature=key,
        organization_id=organization_id,
        enabled=body.enabled,
        actor_user_id=admin.id,
        action=AuditAction.FEATURE_ORGANIZATION_SET,
    )
    return await list_features(admin)


# -- organisations ------------------------------------------------------------


@router.get(
    "/organizations",
    response_model=AdminOrganizationListResponse,
    include_in_schema=False,
)
async def list_organizations(
    _admin: PlatformAdmin,
    search: Annotated[str | None, Query(max_length=200)] = None,
    page: Page = 1,
    limit: Limit = 50,
) -> AdminOrganizationListResponse:
    rows, total = await db_client.list_admin_organizations(
        search=search, limit=limit, offset=(page - 1) * limit
    )
    return AdminOrganizationListResponse(
        organizations=[_organization(row) for row in rows],
        total=total,
        page=page,
        limit=limit,
        default_concurrency_limit=_default_concurrency_limit(),
    )


@router.get(
    "/organizations/{organization_id}",
    response_model=AdminOrganizationDetailResponse,
    include_in_schema=False,
)
async def get_organization(
    organization_id: int, _admin: PlatformAdmin
) -> AdminOrganizationDetailResponse:
    row = await db_client.get_admin_organization(organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    members = await db_client.list_admin_organization_members(organization_id)
    calls = await db_client.list_admin_runs(organization_id=organization_id, limit=20)
    ledger: list[AdminLedgerEntry] | None = None
    ledger_total = 0
    if constants.BILLING_PROVIDER == "stripe":
        entries, ledger_total = await db_client.list_billing_ledger_entries(
            organization_id, limit=50
        )
        ledger = [_ledger_entry(entry) for entry in entries]
    platform, overrides = await db_client.get_feature_flag_values(organization_id)
    return AdminOrganizationDetailResponse(
        organization=_organization(row),
        members=[AdminOrganizationMember(**member) for member in members],
        recent_calls=[_run(call) for call in calls],
        ledger=ledger,
        ledger_total=ledger_total,
        features=features.effective_flags(platform, overrides),
        feature_overrides={
            k: v for k, v in overrides.items() if k in features.FEATURES
        },
    )


@router.put(
    "/organizations/{organization_id}/concurrency-limit",
    response_model=ConcurrencyLimitResponse,
    include_in_schema=False,
)
async def set_concurrency_limit(
    organization_id: int, body: SetConcurrencyLimitRequest, admin: PlatformAdmin
) -> ConcurrencyLimitResponse:
    """How many calls the organisation may run at once (``limit: null`` goes
    back to DEFAULT_ORG_CONCURRENCY_LIMIT). Applies to the next call."""
    await _require_organization(organization_id)
    await db_client.set_organization_concurrency_limit(
        organization_id=organization_id, limit=body.limit, actor_user_id=admin.id
    )
    return ConcurrencyLimitResponse(
        organization_id=organization_id,
        concurrency_limit=body.limit,
        effective_concurrency_limit=(
            body.limit if body.limit is not None else _default_concurrency_limit()
        ),
    )


# -- users ----------------------------------------------------------------------


@router.get("/users", response_model=AdminUserListResponse, include_in_schema=False)
async def list_users(
    _admin: PlatformAdmin,
    search: Annotated[str | None, Query(max_length=200)] = None,
    platform_admins_only: bool = False,
    page: Page = 1,
    limit: Limit = 50,
) -> AdminUserListResponse:
    rows, total = await db_client.list_admin_users(
        search=search,
        platform_admins_only=platform_admins_only,
        limit=limit,
        offset=(page - 1) * limit,
    )
    impersonation_available = constants.AUTH_PROVIDER != "local"
    return AdminUserListResponse(
        users=[
            AdminUser(
                id=row.id,
                email=row.email,
                name=row.name,
                is_platform_admin=row.is_platform_admin,
                email_verified=row.email_verified_at is not None,
                created_at=row.created_at,
                memberships=[
                    AdminUserMembership(
                        organization_id=m.organization_id,
                        organization_name=m.organization_name,
                        role=m.role,
                    )
                    for m in row.memberships
                ],
            )
            for row in rows
        ],
        total=total,
        page=page,
        limit=limit,
        impersonation_available=impersonation_available,
        impersonation_note=(
            None if impersonation_available else IMPERSONATION_UNAVAILABLE_LOCAL
        ),
    )


@router.put(
    "/users/{user_id}/platform-admin",
    response_model=SetPlatformAdminResponse,
    include_in_schema=False,
)
async def set_platform_admin(
    user_id: int, body: SetPlatformAdminRequest, admin: PlatformAdmin
) -> SetPlatformAdminResponse:
    """Grant or revoke platform admin. You cannot revoke your own, and the
    last platform admin cannot be revoked (409)."""
    changed = await db_client.set_platform_admin(
        target_user_id=user_id,
        is_platform_admin=body.is_platform_admin,
        actor_user_id=admin.id,
    )
    return SetPlatformAdminResponse(
        user_id=user_id, is_platform_admin=body.is_platform_admin, changed=changed
    )


# -- audit log ------------------------------------------------------------------


@router.get("/audit-log", response_model=AdminAuditLogResponse, include_in_schema=False)
async def list_audit_log(
    _admin: PlatformAdmin,
    organization_id: int | None = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    page: Page = 1,
    limit: Limit = 50,
) -> AdminAuditLogResponse:
    entries, total = await db_client.list_platform_audit_entries(
        limit=limit,
        offset=(page - 1) * limit,
        organization_id=organization_id,
        action_prefix=action,
    )
    return AdminAuditLogResponse(
        entries=[
            AdminAuditEntry(
                id=e.id,
                created_at=e.created_at,
                action=e.action,
                actor_user_id=e.actor_user_id,
                actor_email=e.actor_email,
                organization_id=e.organization_id,
                organization_name=e.organization_name,
                target_user_id=e.target_user_id,
                target_user_email=e.target_user_email,
                details=e.details,
            )
            for e in entries
        ],
        total=total,
        page=page,
        limit=limit,
    )
