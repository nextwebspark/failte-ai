"""How callers reach an agent: the owner's choice, and whether it works yet.

The choice is stored on the agent's number, under
``telephony_phone_numbers.extra_metadata.phone_setup``:

* ``method`` - ``keep_existing`` (forward the business's existing number to the
  agent's number), ``mobile`` (forward the owner's mobile) or ``new_number``
  (callers ring the agent's number directly);
* ``forward_when`` - when forwarded calls reach the agent (``no_answer``,
  ``busy``, ``all``, ``outside_hours``); only for the two forwarding methods;
* ``started_at`` - when this setup was chosen. Changing the method or the
  forwarding rule restarts it.

"Check it works" is read from call records, never by placing a call: the step
is done once the number has received an inbound call that reached this agent at
or after ``started_at``.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Mapping, Optional

from api.db import db_client as default_db_client
from api.utils.telephony_address import normalize_telephony_address

PHONE_SETUP_KEY = "phone_setup"

SetupMethod = Literal["keep_existing", "new_number", "mobile"]
ForwardWhen = Literal["no_answer", "busy", "all", "outside_hours"]
FORWARDING_METHODS = ("keep_existing", "mobile")


@dataclass(frozen=True)
class FirstCall:
    run_id: int
    at: datetime
    # The number the call was forwarded from, when the carrier passed it on.
    forwarded_from: Optional[str]


def read_setup(extra_metadata: Optional[Mapping[str, Any]]) -> Optional[dict]:
    setup = (extra_metadata or {}).get(PHONE_SETUP_KEY)
    return dict(setup) if isinstance(setup, dict) else None


def with_setup(
    extra_metadata: Optional[Mapping[str, Any]],
    *,
    method: SetupMethod,
    forward_when: Optional[ForwardWhen],
    now: Optional[datetime] = None,
) -> dict:
    """``extra_metadata`` with the new choice. Keeps ``started_at`` when the
    choice is unchanged, so saving the same thing twice doesn't forget a call
    that already came through."""
    if method not in FORWARDING_METHODS:
        forward_when = None
    previous = read_setup(extra_metadata) or {}
    unchanged = (
        previous.get("method") == method
        and previous.get("forward_when") == forward_when
        and previous.get("started_at")
    )
    started_at = (
        previous["started_at"] if unchanged else (now or datetime.now(UTC)).isoformat()
    )
    setup: dict = {"method": method, "started_at": started_at}
    if forward_when:
        setup["forward_when"] = forward_when
    return {**dict(extra_metadata or {}), PHONE_SETUP_KEY: setup}


def _parse_time(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def forwarded_from(run: Any) -> Optional[str]:
    """The ``ForwardedFrom`` number Twilio adds to a forwarded call's webhook.

    Twilio only sends it when the caller's carrier passes the forwarding number
    on, which not every carrier does, and other providers' payloads have no
    such field here, so None is the common answer.
    """
    logs = getattr(run, "logs", None) or {}
    webhook = logs.get("inbound_webhook") or {}
    raw = webhook.get("raw_webhook_data") or {}
    if not isinstance(raw, dict):
        return None
    value = raw.get("ForwardedFrom")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return normalize_telephony_address(value.strip()).canonical
    except Exception:
        return value.strip()


async def find_first_call(
    *,
    workflow_id: int,
    organization_id: int,
    number: Any,
    db: Any = default_db_client,
) -> Optional[FirstCall]:
    """The first inbound call to ``number`` since its setup was chosen."""
    setup = read_setup(getattr(number, "extra_metadata", None))
    since = _parse_time((setup or {}).get("started_at"))
    if since is None:
        return None
    run = await db.find_first_inbound_run_to_number(
        workflow_id, organization_id, number.address_normalized, since
    )
    if run is None:
        return None
    return FirstCall(
        run_id=run.id, at=run.created_at, forwarded_from=forwarded_from(run)
    )
