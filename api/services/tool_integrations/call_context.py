"""What a call tells the tools service about itself.

On a call's MCP requests to the tools service, and nowhere else, the API
names the phone number of the person on the call (``CONTACT_PHONE_HEADER``).
Tools trust it more than anything the agent passes them: Google Calendar's
``find_appointments`` looks a caller's bookings up by it.

The number is only sent for telephony runs, where the platform itself
records it. Web and chat runs accept context variables from the visitor's
page, so a ``caller_number`` there could name anyone.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import urlsplit

from api import constants
from api.enums import (
    WORKFLOW_RUN_MODES_BY_CHANNEL,
    CallType,
    WorkflowRunChannel,
)

__all__ = ["CONTACT_PHONE_HEADER", "contact_phone", "tools_service_headers"]

CONTACT_PHONE_HEADER = "X-Fallcha-Contact-Phone"

_TELEPHONY_MODES = frozenset(
    WORKFLOW_RUN_MODES_BY_CHANNEL[WorkflowRunChannel.TELEPHONY.value]
)
# Which call-context key holds the other party's number.
_CONTACT_NUMBER_KEYS = {
    CallType.INBOUND.value: "caller_number",
    CallType.OUTBOUND.value: "called_number",
}
# A dialable number: digits with optional +, spaces, brackets and dashes.
# Anything else ("unknown", "anonymous", SIP URIs) is treated as hidden.
_PHONE = re.compile(r"\+?[0-9][0-9 ()\-]{5,30}")


def contact_phone(call_context_vars: Mapping[str, object]) -> str | None:
    """The number of the person on a telephony call, if the call record has
    a usable one: the caller on inbound calls, the person called on outbound
    ones."""
    if call_context_vars.get("provider") not in _TELEPHONY_MODES:
        return None
    direction = call_context_vars.get("direction")
    key = _CONTACT_NUMBER_KEYS.get(direction) if isinstance(direction, str) else None
    number = call_context_vars.get(key) if key is not None else None
    if not isinstance(number, str):
        return None
    number = number.strip()
    return number if _PHONE.fullmatch(number) else None


def tools_service_headers(
    url: str, call_context_vars: Mapping[str, object]
) -> dict[str, str]:
    """Headers to add to a call's MCP session at ``url``: the contact's phone
    number when ``url`` is one of the tools service's MCP endpoints, else
    none (other MCP servers never learn who is calling)."""
    phone = contact_phone(call_context_vars)
    if phone is None or not _is_tools_service_mcp(url):
        return {}
    return {CONTACT_PHONE_HEADER: phone}


def _is_tools_service_mcp(url: str) -> bool:
    base = constants.TOOLS_SERVICE_URL
    if not base:
        return False
    tools, target = urlsplit(base.rstrip("/")), urlsplit(url)
    mcp_root = f"{tools.path}/mcp"
    return (
        (target.scheme, target.netloc) == (tools.scheme, tools.netloc)
        and (target.path == mcp_root or target.path.startswith(f"{mcp_root}/"))
        and not target.query
    )
