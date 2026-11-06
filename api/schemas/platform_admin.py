"""Request and response bodies of the platform admin area
(``/superuser/admin/*``) and the feature switch reads (``/features``)."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from api.enums import BillingPlan, OrgRole


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


# -- feature switches -------------------------------------------------------


class FeatureFlagsResponse(BaseModel):
    """Feature key -> on/off."""

    features: dict[str, bool]


class FeatureOrganizationOverride(BaseModel):
    organization_id: int
    organization_name: str | None
    enabled: bool
    updated_at: datetime


class AdminFeature(BaseModel):
    key: str
    label: str
    description: str
    default: bool
    # What a platform admin stored platform-wide; None: the default applies.
    platform_value: bool | None
    effective_platform_value: bool
    overrides: list[FeatureOrganizationOverride]


class AdminFeaturesResponse(BaseModel):
    features: list[AdminFeature]


class SetFeatureRequest(_Request):
    """``enabled: null`` removes the stored value (back to the default, or to
    the platform-wide value for an organisation override)."""

    enabled: bool | None


# -- organisations ------------------------------------------------------------


class AdminOrganization(BaseModel):
    id: int
    name: str | None
    created_at: datetime | None
    status: Literal["active", "deletion_scheduled", "erased"]
    members_count: int
    last_call_at: datetime | None
    plan: BillingPlan | None
    balance_eur: Decimal | None
    credit_limit_eur: Decimal | None
    price_per_minute_override_eur: Decimal | None
    effective_price_per_minute_eur: Decimal
    # Stored limit, or None when the platform default applies.
    concurrency_limit: int | None
    effective_concurrency_limit: int


class AdminOrganizationListResponse(BaseModel):
    organizations: list[AdminOrganization]
    total: int
    page: int
    limit: int
    default_concurrency_limit: int


class AdminOrganizationMember(BaseModel):
    user_id: int
    email: str | None
    name: str | None
    role: OrgRole
    is_platform_admin: bool
    email_verified: bool
    joined_at: datetime | None


class AdminRun(BaseModel):
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


class AdminLedgerEntry(BaseModel):
    id: int
    entry_type: str
    amount_eur: Decimal
    balance_after_eur: Decimal
    description: str | None
    workflow_run_id: int | None
    created_by: int | None
    created_at: datetime


class AdminOrganizationDetailResponse(BaseModel):
    organization: AdminOrganization
    members: list[AdminOrganizationMember]
    recent_calls: list[AdminRun]
    # None when billing is not Stripe (there is no ledger to show).
    ledger: list[AdminLedgerEntry] | None
    ledger_total: int
    features: dict[str, bool]
    feature_overrides: dict[str, bool]


class SetConcurrencyLimitRequest(_Request):
    """``limit: null`` goes back to the platform default."""

    limit: int | None = Field(ge=1, le=1000)


class ConcurrencyLimitResponse(BaseModel):
    organization_id: int
    concurrency_limit: int | None
    effective_concurrency_limit: int


# -- users ----------------------------------------------------------------------


class AdminUserMembership(BaseModel):
    organization_id: int
    organization_name: str | None
    role: OrgRole


class AdminUser(BaseModel):
    id: int
    email: str | None
    name: str | None
    is_platform_admin: bool
    email_verified: bool
    created_at: datetime | None
    memberships: list[AdminUserMembership]


class AdminUserListResponse(BaseModel):
    users: list[AdminUser]
    total: int
    page: int
    limit: int
    # Last sign-in is not recorded by the app, so it is never listed.
    impersonation_available: bool
    impersonation_note: str | None


class SetPlatformAdminRequest(_Request):
    is_platform_admin: bool


class SetPlatformAdminResponse(BaseModel):
    user_id: int
    is_platform_admin: bool
    changed: bool


# -- health ---------------------------------------------------------------------


class HealthCheck(BaseModel):
    id: str
    label: str
    status: Literal["ok", "warning", "problem"]
    detail: str


class HealthConnectionProblem(BaseModel):
    organization_id: int
    organization_name: str | None
    connection_id: str
    provider: str
    account_label: str | None
    last_error: str | None
    error_code: str | None


class HealthConnections(BaseModel):
    checked: bool
    organizations_checked: int
    problems: list[HealthConnectionProblem]
    note: str | None


class AdminHealthResponse(BaseModel):
    generated_at: datetime
    checks: list[HealthCheck]
    failed_calls_24h: int
    stuck_runs_24h: int
    stuck_runs: list[AdminRun]
    connections: HealthConnections


# -- overview -------------------------------------------------------------------


class OverviewRevenue(BaseModel):
    month: str
    available: bool
    note: str | None = None
    revenue_eur: Decimal = Decimal(0)
    provider_cost_eur: Decimal = Decimal(0)
    margin_eur: Decimal = Decimal(0)
    margin_percent: Decimal | None = None
    charged_calls: int = 0
    uncosted_calls: int = 0


class AdminOverviewResponse(BaseModel):
    generated_at: datetime
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
    revenue: OverviewRevenue


# -- audit log ------------------------------------------------------------------


class AdminAuditEntry(BaseModel):
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


class AdminAuditLogResponse(BaseModel):
    entries: list[AdminAuditEntry]
    total: int
    page: int
    limit: int
