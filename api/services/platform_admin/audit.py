"""What the platform admin audit log records (``platform_admin_audit_log``)."""

from decimal import Decimal
from enum import StrEnum
from typing import Any


class AuditAction(StrEnum):
    FEATURE_PLATFORM_SET = "feature.platform_set"
    FEATURE_ORGANIZATION_SET = "feature.organization_set"
    BILLING_TERMS_UPDATED = "billing.terms_updated"
    BILLING_BALANCE_ADJUSTED = "billing.balance_adjusted"
    CONCURRENCY_LIMIT_SET = "organization.concurrency_limit_set"
    PLATFORM_ADMIN_GRANTED = "user.platform_admin_granted"
    PLATFORM_ADMIN_REVOKED = "user.platform_admin_revoked"
    IMPERSONATION_STARTED = "user.impersonation_started"
    HOME_LAYOUT_PLATFORM_SET = "home_layout.platform_set"


def json_safe(value: Any) -> Any:
    """Audit details are stored as JSON: money as strings, enums as values."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value
