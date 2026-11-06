"""Health checks of the platform admin area (no database)."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from api.errors.integrations import ToolsServiceUnavailableError
from api.schemas.integrations import IntegrationConnection
from api.services.platform_admin.health import (
    CheckStatus,
    HealthSettings,
    config_checks,
    scan_integration_connections,
)

HEALTHY = HealthSettings(
    email_provider="resend",
    billing_provider="stripe",
    stripe_secret_key_set=True,
    stripe_webhook_secret_set=True,
    public_base_url="https://app.lightmove.ai",
    tools_service_url="http://fallcha-tools:8000",
    tools_internal_secret_set=True,
    sentry_dsn_set=True,
    sentry_active=True,
    auth_provider="stack",
    jwt_secret_is_default=True,
)


def _status(settings: HealthSettings) -> dict[str, CheckStatus]:
    return {check.id: check.status for check in config_checks(settings)}


def test_a_healthy_configuration_has_no_findings():
    assert set(_status(HEALTHY).values()) == {CheckStatus.OK}
    # The default JWT secret only matters with local sign-in.
    assert "jwt_secret" not in _status(HEALTHY)


@pytest.mark.parametrize(
    ("change", "check", "expected"),
    [
        ({"email_provider": "none"}, "email", CheckStatus.PROBLEM),
        ({"billing_provider": "none"}, "billing", CheckStatus.WARNING),
        ({"stripe_webhook_secret_set": False}, "billing", CheckStatus.PROBLEM),
        (
            {"billing_provider": "mps", "stripe_secret_key_set": False},
            "billing",
            CheckStatus.OK,
        ),
        ({"public_base_url": None}, "public_url", CheckStatus.PROBLEM),
        (
            {"public_base_url": "http://localhost:3010"},
            "public_url",
            CheckStatus.PROBLEM,
        ),
        ({"public_base_url": "http://127.0.0.1"}, "public_url", CheckStatus.PROBLEM),
        (
            {"public_base_url": "http://app.localhost"},
            "public_url",
            CheckStatus.PROBLEM,
        ),
        ({"tools_internal_secret_set": False}, "tools", CheckStatus.PROBLEM),
        ({"tools_service_url": None}, "tools", CheckStatus.WARNING),
        ({"sentry_active": False}, "sentry", CheckStatus.WARNING),
        (
            {"sentry_active": False, "sentry_dsn_set": False},
            "sentry",
            CheckStatus.WARNING,
        ),
        ({"auth_provider": "local"}, "jwt_secret", CheckStatus.PROBLEM),
    ],
)
def test_each_misconfiguration_is_reported(change, check, expected):
    assert _status(replace(HEALTHY, **change))[check] is expected


def test_problem_details_name_the_setting():
    checks = {c.id: c for c in config_checks(replace(HEALTHY, email_provider="none"))}
    assert "EMAIL_PROVIDER" in checks["email"].detail


def _connection(
    status: str, provider: str = "google-calendar"
) -> IntegrationConnection:
    now = datetime.now(UTC)
    return IntegrationConnection(
        id=uuid.uuid4(),
        provider=provider,
        auth_mode="oauth2",
        status=status,
        last_error="invalid_grant" if status == "error" else None,
        created_at=now,
        updated_at=now,
    )


class _FakeTools:
    def __init__(self, by_org):
        self.by_org = by_org
        self.callers = []

    async def list_connections(self, caller):
        self.callers.append(caller)
        result = self.by_org[caller.org_id]
        if isinstance(result, Exception):
            raise result
        return result


async def test_scan_reports_connections_in_error_only():
    tools = _FakeTools(
        {
            1: [_connection("active"), _connection("error")],
            2: [_connection("revoked")],
            3: ToolsServiceUnavailableError(),
        }
    )
    scan = await scan_integration_connections(
        [1, 2, 3],
        tools_service_url="http://tools",
        tools_internal_secret="secret",
        client=tools,
    )
    assert scan.checked is True
    assert scan.organizations_checked == 3
    assert [(p.organization_id, p.last_error) for p in scan.problems] == [
        (1, "invalid_grant")
    ]
    assert "Could not read 1 organisation(s): 3" in scan.note
    # A system read: no acting user.
    assert {caller.user_id for caller in tools.callers} == {0}


async def test_scan_is_skipped_without_the_tools_service():
    scan = await scan_integration_connections(
        [1], tools_service_url="http://tools", tools_internal_secret=None
    )
    assert scan.checked is False
    assert scan.problems == []
