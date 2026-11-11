"""Tell someone when something critical fails.

Every classified failure is already logged by ``api.errors.failure.log_failure``
(one ``DOGRAH_FAILURE`` line with source, type, code and owner). This module
adds the alert for the ones that need a person:

- **Workspace alerts** go to the workspace's admins and owners when the
  failure is theirs to fix: a configuration problem (a number with no agent,
  a calendar that can't be read), credit used up, or their own provider
  account failing. ``ErrorOwner.USER``, types config/quota/provider.
- **Operator alerts** go to the founders when the failure is ours:
  ``ErrorOwner.OPERATOR`` (platform or system errors). Recipients are
  ``OPERATOR_ALERT_EMAILS`` (comma-separated), else every platform admin.

Failures marked ``notification_eligible: False`` never alert (e.g. a bad
webhook signature, which anyone on the internet can trigger).

Alerts are sent by a background job, never on the failing path, and each
(recipient group, workspace, failure code) is sent at most once per
``ALERT_REPEAT_HOURS``: the process skips repeats it already queued, and the
job claims a Redis key before sending, so several workers send one email.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

from loguru import logger

from api.errors.failure import DograhFailure, ErrorOwner, ErrorType

AlertTarget = Literal["workspace", "operator"]
ALERT_REPEAT_HOURS = 6
_WORKSPACE_TYPES = frozenset(
    {ErrorType.CONFIG_ERROR, ErrorType.QUOTA_ERROR, ErrorType.PROVIDER_ERROR}
)
# Process-local memory of alerts already queued: (key) -> monotonic time.
_recently_queued: dict[str, float] = {}


@dataclass(frozen=True, slots=True)
class FailureAlert:
    """What the alert job needs; plain values, so it can be queued."""

    target: AlertTarget
    organization_id: int | None
    source: str
    type: str
    code: str
    provider: str | None
    message: str

    @property
    def dedupe_key(self) -> str:
        scope = self.organization_id if self.organization_id is not None else "platform"
        return f"failure-alert:{self.target}:{scope}:{self.code}"


def alert_for(failure: DograhFailure, context: dict[str, Any]) -> FailureAlert | None:
    """The alert this failure should raise, or None."""
    if context.get("notification_eligible") is False:
        return None
    org_id = context.get("organization_id")
    organization_id = org_id if isinstance(org_id, int) else None
    owner = failure.error_owner
    if owner == ErrorOwner.OPERATOR:
        target: AlertTarget = "operator"
        message = failure.internal_message
    elif (
        owner == ErrorOwner.USER
        and failure.type in _WORKSPACE_TYPES
        and organization_id is not None
    ):
        target = "workspace"
        message = failure.external_message
    else:
        return None
    return FailureAlert(
        target=target,
        organization_id=organization_id,
        source=failure.source.value,
        type=failure.type.value,
        code=failure.code,
        provider=failure.provider,
        message=message,
    )


def _already_queued(key: str, now: float) -> bool:
    last = _recently_queued.get(key)
    if last is not None and now - last < ALERT_REPEAT_HOURS * 3600:
        return True
    _recently_queued[key] = now
    if len(_recently_queued) > 5000:  # bound memory on a long-lived process
        _recently_queued.clear()
        _recently_queued[key] = now
    return False


def on_failure(failure: DograhFailure, context: dict[str, Any]) -> None:
    """Failure listener: queue an alert job if this failure needs one.

    Never raises and never waits: it only schedules the enqueue on the
    running event loop (no loop, no alert; the failure is still logged)."""
    alert = alert_for(failure, context)
    if alert is None or _already_queued(alert.dedupe_key, time.monotonic()):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_enqueue(alert))


async def _enqueue(alert: FailureAlert) -> None:
    from api.tasks.arq import enqueue_job
    from api.tasks.function_names import FunctionNames

    try:
        await enqueue_job(FunctionNames.SEND_FAILURE_ALERT, asdict(alert))
    except Exception as exc:
        logger.warning(f"Could not queue failure alert {alert.dedupe_key}: {exc!r}")


def operator_recipients_from_env(env: dict[str, str] | None = None) -> list[str]:
    raw = (env if env is not None else os.environ).get("OPERATOR_ALERT_EMAILS", "")
    return [e.strip() for e in raw.split(",") if "@" in e]


async def send_failure_alert(ctx: dict, payload: dict) -> str:
    """ARQ job: claim the alert, find recipients, send one email."""
    from api.constants import UI_APP_URL
    from api.db import db_client
    from api.enums import OrgRole
    from api.services.email import get_email_sender
    from api.services.email.templates import failure_alert_message

    alert = FailureAlert(**payload)
    redis = ctx.get("redis")
    if redis is not None:
        claimed = await redis.set(
            alert.dedupe_key, "1", ex=ALERT_REPEAT_HOURS * 3600, nx=True
        )
        if not claimed:
            return "duplicate"

    organization_name: str | None = None
    if alert.organization_id is not None:
        organization = await db_client.get_organization_by_id(alert.organization_id)
        organization_name = organization.name if organization else None

    if alert.target == "workspace":
        members = await db_client.list_organization_members(alert.organization_id)
        recipients = [
            m.email
            for m in members
            if m.email and m.role in (OrgRole.ADMIN, OrgRole.VIEWER)
        ]
    else:
        recipients = operator_recipients_from_env() or [
            u.email for u in await db_client.list_platform_admins() if u.email
        ]
    if not recipients:
        logger.warning(f"No one to send failure alert {alert.dedupe_key} to")
        return "no_recipients"

    sender = get_email_sender()
    sent = 0
    for to in sorted(set(recipients)):
        message = failure_alert_message(
            to=to,
            for_operator=alert.target == "operator",
            organization_name=organization_name,
            source=alert.source,
            code=alert.code,
            provider=alert.provider,
            detail=alert.message,
            app_url=UI_APP_URL,
        )
        try:
            await sender.send(message)
            sent += 1
        except Exception as exc:
            logger.error(f"Failure alert {alert.dedupe_key} to {to} not sent: {exc!r}")
    logger.info(f"Failure alert {alert.dedupe_key} sent to {sent} recipient(s)")
    return f"sent:{sent}"
