"""What a call tells the tools service about itself.

On a call's MCP requests to the tools service, and nowhere else, the API
names the phone number of the person on the call (``CONTACT_PHONE_HEADER``).
Google Calendar's ``find_appointments`` uses it so the caller is not asked
for their number (their name is still always required: caller ID can be
spoofed).

The number is taken once, at the authenticated telephony entry point, from
the run row as the telephony code created it and its ``call_type`` column
(:func:`telephony_contact_phone`), before template, external or pre-call
fetch variables are merged into the call context. Web and chat runs never
have one: their context variables come from the visitor's page or the
workflow editor.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from types import MappingProxyType
from urllib.parse import urlsplit

from api import constants
from api.enums import CallType

__all__ = ["CONTACT_PHONE_HEADER", "telephony_contact_phone", "tools_service_headers"]

CONTACT_PHONE_HEADER = "X-Fallcha-Contact-Phone"

# Per direction: (context key of the other party's number, of the business's).
_NUMBER_KEYS: Mapping[CallType, tuple[str, str]] = MappingProxyType(
    {
        CallType.INBOUND: ("caller_number", "called_number"),
        CallType.OUTBOUND: ("called_number", "caller_number"),
    }
)
# A dialable number: digits with optional +, spaces, brackets and dashes.
# Anything else ("unknown", "anonymous", SIP URIs) is treated as hidden.
_PHONE = re.compile(r"\+?[0-9][0-9 ()\-]{5,30}")
# Twilio turns a withheld caller ID's placeholder word into keypad digits
# for From (support.twilio.com, "Why am I getting calls from these strange
# numbers?"): ANONYMOUS, RESTRICTED, BLOCKED, UNKNOWN.
_WITHHELD_DIGITS = frozenset({"266696687", "7378742833", "2562533", "8656696"})
# Numbers agreeing in this many trailing digits are the same line (formats
# differ: +353 1 555 0000 and 01 555 0000).
_SAME_LINE_DIGITS = 8


def telephony_contact_phone(
    call_type: object, initial_context: Mapping[str, object] | None
) -> str | None:
    """The number of the person on a telephony call: the caller on inbound
    calls, the person called on outbound ones; None when hidden, withheld,
    unusable or the business's own number.

    ``call_type`` is the run's ``call_type`` column and ``initial_context``
    the run row's context as the telephony code created it; call this before
    anything else is merged into it.
    """
    direction = _call_type(call_type)
    if direction is None:
        return None
    contact_key, own_key = _NUMBER_KEYS[direction]
    context = initial_context or {}
    contact = _dialable(context.get(contact_key))
    if contact is None or _digits(contact) in _WITHHELD_DIGITS:
        return None
    own = _dialable(context.get(own_key))
    if own is not None and _same_line(contact, own):
        return None
    return contact


def tools_service_headers(url: str, contact_phone: str | None) -> dict[str, str]:
    """Headers to add to a call's MCP session at ``url``: the contact's phone
    number when ``url`` is one of the tools service's MCP endpoints, else
    none (other MCP servers never learn who is calling)."""
    if contact_phone is None or not _is_tools_service_mcp(url):
        return {}
    return {CONTACT_PHONE_HEADER: contact_phone}


def _call_type(value: object) -> CallType | None:
    raw = value.value if isinstance(value, CallType) else value
    try:
        return CallType(raw)
    except ValueError:
        return None


def _dialable(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    number = value.strip()
    return number if _PHONE.fullmatch(number) else None


def _digits(number: str) -> str:
    return "".join(ch for ch in number if ch.isdigit())


def _same_line(first: str, second: str) -> bool:
    return _digits(first)[-_SAME_LINE_DIGITS:] == _digits(second)[-_SAME_LINE_DIGITS:]


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
