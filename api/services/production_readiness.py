"""Refuse to start a production API that would silently fail customers.

Each of these settings has a harmless-looking default that is fine on a
laptop and quietly broken in production:

- EMAIL_PROVIDER=none: sign-up codes, password resets, invitations and
  low-credit warnings are only logged, so nobody can finish signing up.
- BILLING_PROVIDER=none: calls are free and unlimited.
- UI_APP_URL / BACKEND_API_ENDPOINT on localhost: links in emails and Stripe
  return pages point at localhost.

With ENVIRONMENT=production the API stops at startup and names what is
missing. ALLOW_INCOMPLETE_PRODUCTION_CONFIG=true starts it anyway (with the
same problems logged as errors), for an operator who means it, e.g. a
deployment that deliberately runs without billing.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlparse

from loguru import logger

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})
OVERRIDE = "ALLOW_INCOMPLETE_PRODUCTION_CONFIG"


class ProductionConfigError(RuntimeError):
    pass


def _is_local(url: str | None) -> bool:
    if not url:
        return True
    host = (urlparse(url).hostname or "").lower()
    return host in _LOCAL_HOSTS


def production_config_problems(
    *,
    email_provider: str,
    billing_provider: str,
    ui_app_url: str | None,
    backend_api_endpoint: str | None,
) -> list[str]:
    """What would break for customers, in plain words; empty when ready."""
    problems: list[str] = []
    if email_provider.strip().lower() in ("", "none"):
        problems.append(
            "EMAIL_PROVIDER is none: sign-up codes, password resets and "
            "invitations would never be delivered (set the Resend key)"
        )
    if billing_provider.strip().lower() in ("", "none"):
        problems.append(
            "BILLING_PROVIDER is none: calls would be free and unlimited "
            "(set the Stripe keys)"
        )
    if _is_local(ui_app_url):
        problems.append(
            f"UI_APP_URL is {ui_app_url or 'unset'}: links in emails and "
            "payment pages would point at localhost (set PUBLIC_BASE_URL)"
        )
    if _is_local(backend_api_endpoint):
        problems.append(
            f"BACKEND_API_ENDPOINT is {backend_api_endpoint or 'unset'}: "
            "telephony callbacks would point at localhost (set PUBLIC_BASE_URL)"
        )
    return problems


def check_production_config(env: Mapping[str, str] | None = None) -> list[str]:
    """Run at startup. Raises ProductionConfigError in production when a
    setting would silently fail customers, unless the operator overrides."""
    from api import constants

    env = os.environ if env is None else env
    if constants.ENVIRONMENT != "production":
        return []
    problems = production_config_problems(
        email_provider=env.get("EMAIL_PROVIDER", "none"),
        billing_provider=constants.BILLING_PROVIDER,
        ui_app_url=constants.UI_APP_URL,
        backend_api_endpoint=constants.BACKEND_API_ENDPOINT,
    )
    if not problems:
        return []
    if env.get(OVERRIDE, "").strip().lower() == "true":
        for problem in problems:
            logger.error(f"Production config: {problem} ({OVERRIDE}=true)")
        return problems
    # The process is about to stop, so nothing can be emailed: a CRITICAL log
    # line is what the platform's log alerting (and Sentry, if on) picks up.
    for problem in problems:
        logger.critical(f"Production config: {problem}")
    raise ProductionConfigError(
        "Refusing to start in production:\n- "
        + "\n- ".join(problems)
        + f"\nFix these, or set {OVERRIDE}=true to start anyway."
    )
