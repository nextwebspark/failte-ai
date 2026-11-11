"""Callers who rang while every line was busy (the business's "calls at
once" limit was reached): what we do with them, and how the call is kept.

When an inbound call can't get an agent slot, the call is not lost:

* **forward** - put straight through to the agent's "Pass calls to your
  team" number with the provider's own dial verb (no AI, no slot), when the
  number may be dialled and the business is open (or the owner passes calls
  at any time);
* **voicemail** - a short line, then the provider records a message;
* **busy_message** - just the busy line (today's behaviour).

The owner picks one under "Pass calls to your team" ("When all lines are
busy"). It is kept with the agent's facts (``LINES_BUSY_KEY``), so it needs
no table or migration. Left unset: forward when there is a number, else
voicemail.

Every turned-away call is stored as an inbound workflow run that never
reached the agent. What happened is written to ``gathered_context`` under
separate top-level keys (one writer each, so two provider callbacks landing
together can't overwrite each other: the run update merges top-level keys
under a row lock):

* ``lines_busy``: the plan, written when the call comes in
  (``action``, ``chosen``, ``reason``, ``limit``, ``forward_to``);
* ``lines_busy_forward``: the forward's result (``result`` "answered" or
  "not_answered", the provider's ``status``, ``seconds`` talked);
* ``lines_busy_voicemail``: the message left (``seconds``, ``stored``).

The run has no ``usage_info.call_duration_seconds``, so billing never
charges it (``billing.charging.billable_seconds`` is 0 and the uncharged-run
sweep skips it), and ``workflow_run_billing`` refuses it outright as well.

Pure: no I/O. ``api.services.telephony.lines_busy`` does the work.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from api.utils.transfer_number import check_transfer_number, to_e164

# The owner's choice, kept with the agent's facts (template context variables).
LINES_BUSY_KEY = "lines_busy_action"
TRANSFER_NUMBER_KEY = "transfer_number"

# Keys on the run's gathered_context (see the module docstring).
PLAN_KEY = "lines_busy"
FORWARD_KEY = "lines_busy_forward"
VOICEMAIL_KEY = "lines_busy_voicemail"
# The outcome code the Calls page shows ("Lines were busy").
DISPOSITION = "lines_busy"

# How long the staff phone rings before we give up and take a message.
FORWARD_RING_SECONDS = 20
# The longest voicemail a caller can leave.
MAX_VOICEMAIL_SECONDS = 90

# What the caller hears. Plain and short: they are already waiting.
FORWARD_LINE = "All our lines are busy, so we're putting you through to the team now."
VOICEMAIL_LINE = (
    "All our lines are busy. Please leave your name and number after the tone "
    "and we'll call you back."
)
FORWARD_FAILED_VOICEMAIL_LINE = (
    "Sorry, nobody from the team could take your call. Please leave your name "
    "and number after the tone and we'll call you back."
)
VOICEMAIL_THANKS = "Thank you. We'll call you back soon. Goodbye."
NO_MESSAGE_GOODBYE = "We didn't get a message. Please try again later. Goodbye."


class LinesBusyAction(StrEnum):
    FORWARD = "forward"
    VOICEMAIL = "voicemail"
    BUSY_MESSAGE = "busy_message"


class LinesBusyOutcome(StrEnum):
    """What came of a turned-away call, for Calls, Follow-ups and Reports."""

    # A person on the team answered the forwarded call.
    FORWARDED = "forwarded"
    # The caller left a voicemail.
    VOICEMAIL = "voicemail"
    # Offered a voicemail (or the forward rang out) and left none.
    NO_MESSAGE = "no_message"
    # Heard the busy line only.
    TOLD_BUSY = "told_busy"


# What a provider can do on a turned-away call (``lines_busy_support``).
SAY = "say"
FORWARD = "forward"
VOICEMAIL = "voicemail"
# Providers that forward and take voicemails (``lines_busy_support`` on each);
# on the rest the caller hears the busy line and the call is still kept.
LINES_BUSY_PROVIDERS = frozenset({"twilio", "telnyx"})


# The provider can't say anything either: the call was just ended
# (Asterisk/ARI hangs up the channel).
HUNG_UP_REASON = "hung_up"


class NotForwardedReason(StrEnum):
    NO_NUMBER = "no_number"
    CLOSED = "closed"
    DEMO_NUMBER = "demo_number"
    OWN_NUMBER = "own_number"
    INVALID_NUMBER = "invalid_number"
    # A PBX address (SIP URI, extension): not dialled from here.
    PHONE_SYSTEM = "phone_system"
    NOT_SUPPORTED = "not_supported"


def stored_choice(facts: Mapping[str, Any] | None) -> LinesBusyAction | None:
    """The owner's choice, or None when they haven't made one."""
    value = (facts or {}).get(LINES_BUSY_KEY)
    try:
        return LinesBusyAction(value) if value else None
    except ValueError:
        return None


def default_action(facts: Mapping[str, Any] | None) -> LinesBusyAction:
    """Forward when the agent has a transfer number, else voicemail."""
    number = (facts or {}).get(TRANSFER_NUMBER_KEY)
    if isinstance(number, str) and number.strip():
        return LinesBusyAction.FORWARD
    return LinesBusyAction.VOICEMAIL


def effective_choice(facts: Mapping[str, Any] | None) -> LinesBusyAction:
    return stored_choice(facts) or default_action(facts)


@dataclass(frozen=True, slots=True)
class ForwardCheck:
    destination: str | None
    reason: NotForwardedReason | None


def forward_destination(
    facts: Mapping[str, Any] | None,
    *,
    own_numbers: Iterable[str],
    closed: bool,
) -> ForwardCheck:
    """The number to forward to, or why the call can't be forwarded. The
    same guards as the transfer tool: never a reserved demo number, never a
    number that rings this agent again (the one the caller rang, or another
    of the agent's numbers), only a number that passes the number check, and
    only while open when the owner passes calls during opening hours."""
    raw = (facts or {}).get(TRANSFER_NUMBER_KEY)
    if not isinstance(raw, str) or not raw.strip():
        return ForwardCheck(None, NotForwardedReason.NO_NUMBER)
    check = check_transfer_number(raw)
    if not check.ok:
        return ForwardCheck(None, NotForwardedReason.INVALID_NUMBER)
    if check.is_demo:
        return ForwardCheck(None, NotForwardedReason.DEMO_NUMBER)
    if check.is_sip:
        return ForwardCheck(None, NotForwardedReason.PHONE_SYSTEM)
    if check.value in {to_e164(n) or n for n in own_numbers if n}:
        return ForwardCheck(None, NotForwardedReason.OWN_NUMBER)
    if closed:
        return ForwardCheck(None, NotForwardedReason.CLOSED)
    return ForwardCheck(check.value, None)


@dataclass(frozen=True, slots=True)
class LinesBusyPlan:
    action: LinesBusyAction
    # What the owner picked (None: the default applied).
    chosen: LinesBusyAction | None
    # Where a forward rings.
    destination: str | None = None
    # Why the owner's choice wasn't followed, e.g. "closed".
    reason: str | None = None
    # A forward nobody answers falls back to a voicemail.
    voicemail_fallback: bool = False

    def as_record(self, limit: int | None) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "chosen": self.chosen.value if self.chosen else None,
            "reason": self.reason,
            "limit": limit,
            "forward_to": self.destination,
            "voicemail_fallback": self.voicemail_fallback,
        }


def plan_lines_busy(
    facts: Mapping[str, Any] | None,
    *,
    support: frozenset[str],
    own_numbers: Iterable[str],
    closed: bool,
) -> LinesBusyPlan:
    """What to do with a caller who can't get an agent slot.

    *support* is what the provider can do (``SAY``, ``FORWARD``,
    ``VOICEMAIL``); *closed* is the opening-hours gate for passing calls
    (``opening_hours.transfer_closed``). A forward that can't happen falls
    back to a voicemail, and a voicemail the provider can't record to the
    busy line."""
    chosen = stored_choice(facts)
    wanted = chosen or default_action(facts)
    can_record = VOICEMAIL in support
    reason: str | None = None

    if wanted == LinesBusyAction.FORWARD:
        if FORWARD not in support:
            reason = NotForwardedReason.NOT_SUPPORTED.value
        else:
            check = forward_destination(facts, own_numbers=own_numbers, closed=closed)
            if check.destination:
                return LinesBusyPlan(
                    LinesBusyAction.FORWARD,
                    chosen,
                    destination=check.destination,
                    voicemail_fallback=can_record,
                )
            reason = check.reason.value if check.reason else None
        wanted = LinesBusyAction.VOICEMAIL

    if wanted == LinesBusyAction.VOICEMAIL:
        if can_record:
            return LinesBusyPlan(LinesBusyAction.VOICEMAIL, chosen, reason=reason)
        reason = reason or NotForwardedReason.NOT_SUPPORTED.value

    return LinesBusyPlan(LinesBusyAction.BUSY_MESSAGE, chosen, reason=reason)


# ------------------------------------------------------------------ reading


def _part(gathered: Mapping[str, Any] | None, key: str) -> Mapping[str, Any]:
    value = (gathered or {}).get(key)
    return value if isinstance(value, Mapping) else {}


def is_lines_busy(gathered: Mapping[str, Any] | None) -> bool:
    """Whether the call was turned away because every line was busy."""
    return bool(_part(gathered, PLAN_KEY).get("action"))


def planned_action(gathered: Mapping[str, Any] | None) -> LinesBusyAction | None:
    try:
        return LinesBusyAction(_part(gathered, PLAN_KEY).get("action"))
    except ValueError:
        return None


def forward_answered(gathered: Mapping[str, Any] | None) -> bool:
    return _part(gathered, FORWARD_KEY).get("result") == "answered"


def voicemail_seconds(gathered: Mapping[str, Any] | None) -> int | None:
    """The voicemail's length when one was left, else None."""
    seconds = _part(gathered, VOICEMAIL_KEY).get("seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        return None
    return int(seconds) if seconds > 0 else None


def left_voicemail(gathered: Mapping[str, Any] | None) -> bool:
    return voicemail_seconds(gathered) is not None


def was_forwarded(gathered: Mapping[str, Any] | None) -> bool:
    """The call rang the team (answered or not)."""
    return planned_action(gathered) == LinesBusyAction.FORWARD


def lines_busy_outcome(gathered: Mapping[str, Any] | None) -> LinesBusyOutcome | None:
    if not is_lines_busy(gathered):
        return None
    if forward_answered(gathered):
        return LinesBusyOutcome.FORWARDED
    if left_voicemail(gathered):
        return LinesBusyOutcome.VOICEMAIL
    if planned_action(gathered) == LinesBusyAction.BUSY_MESSAGE:
        if _part(gathered, PLAN_KEY).get("reason") == HUNG_UP_REASON:
            return LinesBusyOutcome.NO_MESSAGE
        return LinesBusyOutcome.TOLD_BUSY
    return LinesBusyOutcome.NO_MESSAGE


def forward_record(status: str | None, seconds: Any = None) -> dict[str, Any]:
    """``lines_busy_forward`` from the provider's dial status."""
    answered = (status or "").lower() in {"answered", "completed", "bridged"}
    try:
        talked = int(float(seconds)) if seconds not in (None, "") else None
    except (TypeError, ValueError):
        talked = None
    return {
        "result": "answered" if answered else "not_answered",
        "status": status,
        "seconds": talked,
    }
