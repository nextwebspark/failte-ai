"""Checks the transfer tool makes on a resolved destination before dialling,
and the caller-ID choice for the leg that rings the staff phone."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from api.utils.transfer_number import (
    SHOW_CALLER_NUMBER_KEY,
    SHOW_CALLER_NUMBER_OFF,
    is_demo_number,
    is_sip_destination,
    to_e164,
)

# What the agent hears back: the same shape as a transfer nobody answered,
# so it takes a message, and Home / Follow-ups count it as not answered.
_NOT_ANSWERED_MESSAGE = (
    "Nobody on the team could take the call right now. Offer to take a message instead."
)


def transfer_guard_result(
    destination: str, call_context_vars: Optional[Mapping[str, Any]]
) -> Optional[Dict[str, Any]]:
    """A failed transfer result when *destination* must not be dialled, else
    None.

    - A reserved demo number is never dialled, whoever set it: a
      valid-looking fake could be someone's real phone (reason
      ``demo_number``).
    - The number the caller rang would ring this agent again, round in a
      circle (reason ``own_number``).
    """
    if is_demo_number(destination):
        return {
            "status": "failed",
            "message": _NOT_ANSWERED_MESSAGE,
            "action": "transfer_failed",
            "reason": "demo_number",
        }
    context = call_context_vars or {}
    called = context.get("called_number")
    if (
        context.get("direction") == "inbound"
        and isinstance(called, str)
        and called
        and not is_sip_destination(destination)
    ):
        dialled = to_e164(destination)
        if dialled and dialled == to_e164(called):
            return {
                "status": "failed",
                "message": _NOT_ANSWERED_MESSAGE,
                "action": "transfer_failed",
                "reason": "own_number",
            }
    return None


def caller_number_params(
    provider: Any,
    workflow_run: Any,
    call_context_vars: Optional[Mapping[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Provider parameters that make the staff phone show the caller's number,
    or None to keep the agent's own number (today's behaviour).

    Only for inbound calls, when the agent's "Show the caller's number when
    we pass a call to you" option is on (the default), and when the provider
    can do it from the inbound call's own webhook (``transfer_caller_number_
    params``; Twilio and Telnyx).
    """
    context = call_context_vars or {}
    if context.get(SHOW_CALLER_NUMBER_KEY) == SHOW_CALLER_NUMBER_OFF:
        return None
    if context.get("direction") != "inbound":
        return None
    build = getattr(provider, "transfer_caller_number_params", None)
    if build is None:
        return None
    inbound = ((getattr(workflow_run, "logs", None) or {}).get("inbound_webhook")) or {}
    raw = inbound.get("raw_webhook_data") if isinstance(inbound, dict) else None
    if not isinstance(raw, dict):
        return None
    try:
        params = build(raw)
    except Exception:
        return None
    return params if isinstance(params, dict) and params else None
