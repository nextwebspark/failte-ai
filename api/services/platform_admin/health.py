"""Operational health for the platform admin area.

``config_checks`` is pure (it reads a settings snapshot), so it is unit
tested without a database. The rest gathers counts from the database and the
tools service.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

from loguru import logger

from api.errors.domain import DomainError
from api.services.tool_integrations.client import Caller, ToolsServiceClient

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}
# The default OSS_JWT_SECRET in api/constants.py.
_DEFAULT_JWT_SECRET = "change-me-in-production"


class CheckStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    PROBLEM = "problem"


@dataclass(frozen=True, slots=True)
class ConfigCheck:
    id: str
    label: str
    status: CheckStatus
    detail: str


@dataclass(frozen=True, slots=True)
class HealthSettings:
    """The configuration values the checks read, as plain values."""

    email_provider: str
    billing_provider: str
    stripe_secret_key_set: bool
    stripe_webhook_secret_set: bool
    public_base_url: str | None
    tools_service_url: str | None
    tools_internal_secret_set: bool
    sentry_dsn_set: bool
    sentry_active: bool
    auth_provider: str
    jwt_secret_is_default: bool


def settings_from_environment(env: Mapping[str, str]) -> HealthSettings:
    """Snapshot of the running configuration. Values come from
    ``api.constants`` where the app reads them there, so this reports what
    the app actually uses."""
    from api import constants

    sentry_dsn_set = bool(constants.SENTRY_DSN)
    return HealthSettings(
        email_provider=(env.get("EMAIL_PROVIDER") or "none").strip().lower(),
        billing_provider=constants.BILLING_PROVIDER,
        stripe_secret_key_set=bool(constants.STRIPE_SECRET_KEY),
        stripe_webhook_secret_set=bool(constants.STRIPE_WEBHOOK_SECRET),
        public_base_url=constants.PUBLIC_BASE_URL,
        tools_service_url=env.get("TOOLS_SERVICE_URL") or None,
        tools_internal_secret_set=bool(constants.TOOLS_INTERNAL_SECRET),
        sentry_dsn_set=sentry_dsn_set,
        # Same condition as the sentry_sdk.init call in api/app.py.
        sentry_active=sentry_dsn_set
        and (constants.DEPLOYMENT_MODE != "oss" or constants.ENABLE_TELEMETRY),
        auth_provider=constants.AUTH_PROVIDER,
        jwt_secret_is_default=constants.OSS_JWT_SECRET == _DEFAULT_JWT_SECRET,
    )


def _is_local_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in _LOCAL_HOSTS or host.endswith(".localhost")


def config_checks(settings: HealthSettings) -> list[ConfigCheck]:
    checks: list[ConfigCheck] = []

    def add(check_id: str, label: str, status: CheckStatus, detail: str) -> None:
        checks.append(ConfigCheck(check_id, label, status, detail))

    if settings.email_provider in ("", "none"):
        add(
            "email",
            "Email",
            CheckStatus.PROBLEM,
            "EMAIL_PROVIDER is none: invitations, verification and password "
            "reset emails are only written to the log.",
        )
    else:
        add("email", "Email", CheckStatus.OK, f"Sent with {settings.email_provider}.")

    if settings.billing_provider == "none":
        add(
            "billing",
            "Billing",
            CheckStatus.WARNING,
            "BILLING_PROVIDER is none: calls are not charged and the billing "
            "actions in this area are unavailable.",
        )
    elif settings.billing_provider == "stripe" and not (
        settings.stripe_secret_key_set and settings.stripe_webhook_secret_set
    ):
        missing = [
            name
            for name, present in (
                ("STRIPE_SECRET_KEY", settings.stripe_secret_key_set),
                ("STRIPE_WEBHOOK_SECRET", settings.stripe_webhook_secret_set),
            )
            if not present
        ]
        add(
            "billing",
            "Billing",
            CheckStatus.PROBLEM,
            f"BILLING_PROVIDER is stripe but {', '.join(missing)} is not set.",
        )
    else:
        add(
            "billing",
            "Billing",
            CheckStatus.OK,
            f"BILLING_PROVIDER is {settings.billing_provider}.",
        )

    if not settings.public_base_url:
        add(
            "public_url",
            "Public URL",
            CheckStatus.PROBLEM,
            "PUBLIC_BASE_URL is not set: links in emails and telephony "
            "callbacks fall back to localhost.",
        )
    elif _is_local_url(settings.public_base_url):
        add(
            "public_url",
            "Public URL",
            CheckStatus.PROBLEM,
            f"PUBLIC_BASE_URL points at this machine ({settings.public_base_url}).",
        )
    else:
        add("public_url", "Public URL", CheckStatus.OK, settings.public_base_url)

    tools_missing = [
        name
        for name, present in (
            ("TOOLS_SERVICE_URL", bool(settings.tools_service_url)),
            ("TOOLS_INTERNAL_SECRET", settings.tools_internal_secret_set),
        )
        if not present
    ]
    if not settings.tools_internal_secret_set:
        add(
            "tools",
            "Integrations (tools service)",
            CheckStatus.PROBLEM,
            f"{', '.join(tools_missing)} not set: integrations such as Google "
            "Calendar are switched off.",
        )
    elif tools_missing:
        add(
            "tools",
            "Integrations (tools service)",
            CheckStatus.WARNING,
            "TOOLS_SERVICE_URL is not set; the default http://fallcha-tools:8000 "
            "is used.",
        )
    else:
        add(
            "tools",
            "Integrations (tools service)",
            CheckStatus.OK,
            "TOOLS_SERVICE_URL and TOOLS_INTERNAL_SECRET are set.",
        )

    if settings.sentry_active:
        add("sentry", "Error reporting (Sentry)", CheckStatus.OK, "Sentry is on.")
    elif settings.sentry_dsn_set:
        add(
            "sentry",
            "Error reporting (Sentry)",
            CheckStatus.WARNING,
            "SENTRY_DSN is set but ENABLE_TELEMETRY=false keeps Sentry off in "
            "oss mode.",
        )
    else:
        add(
            "sentry",
            "Error reporting (Sentry)",
            CheckStatus.WARNING,
            "SENTRY_DSN is not set: server errors are only in the logs.",
        )

    if settings.auth_provider == "local" and settings.jwt_secret_is_default:
        add(
            "jwt_secret",
            "Sign-in secret",
            CheckStatus.PROBLEM,
            "OSS_JWT_SECRET is the default value: anyone who knows it can sign "
            "in as any user.",
        )

    return checks


@dataclass(frozen=True, slots=True)
class ConnectionProblem:
    organization_id: int
    connection_id: str
    provider: str
    account_label: str | None
    last_error: str | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class ConnectionScan:
    checked: bool
    organizations_checked: int
    problems: list[ConnectionProblem]
    # Why the scan did not run, or which organisations could not be read.
    note: str | None


# Organisations read per health check, and at once.
MAX_ORGANIZATIONS_SCANNED = 200
_CONCURRENCY = 5


async def scan_integration_connections(
    organization_ids: list[int],
    *,
    tools_service_url: str | None,
    tools_internal_secret: str | None,
    client: ToolsServiceClient | None = None,
) -> ConnectionScan:
    """Connections in ``error`` across organisations with an installed
    integration, read from the tools service."""
    if not tools_internal_secret or not tools_service_url:
        return ConnectionScan(False, 0, [], "The tools service is not configured.")
    if client is None:
        client = ToolsServiceClient(
            base_url=tools_service_url, internal_secret=tools_internal_secret
        )
    scanned = organization_ids[:MAX_ORGANIZATIONS_SCANNED]
    semaphore = asyncio.Semaphore(_CONCURRENCY)
    failures: list[int] = []

    async def read(organization_id: int) -> list[ConnectionProblem]:
        async with semaphore:
            try:
                # user_id 0: a system read with no acting user.
                connections = await client.list_connections(
                    Caller(org_id=organization_id, user_id=0)
                )
            except DomainError as exc:
                logger.warning(
                    f"Health: could not read connections of org {organization_id}: "
                    f"{exc.message}"
                )
                failures.append(organization_id)
                return []
        return [
            ConnectionProblem(
                organization_id=organization_id,
                connection_id=str(connection.id),
                provider=connection.provider,
                account_label=connection.account_label,
                last_error=connection.last_error,
                error_code=connection.error_code,
            )
            for connection in connections
            if connection.status == "error"
        ]

    results = await asyncio.gather(*(read(org_id) for org_id in scanned))
    notes = []
    if failures:
        notes.append(
            f"Could not read {len(failures)} organisation(s): "
            + ", ".join(str(i) for i in sorted(failures)[:10])
        )
    if len(organization_ids) > len(scanned):
        notes.append(
            f"Checked the first {len(scanned)} of {len(organization_ids)} "
            "organisations with integrations."
        )
    return ConnectionScan(
        checked=True,
        organizations_checked=len(scanned),
        problems=[problem for result in results for problem in result],
        note=" ".join(notes) or None,
    )
