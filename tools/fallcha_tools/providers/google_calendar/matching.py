"""Which bookings belong to a caller: pure matching rules, no I/O.

A caller is identified by the phone number the appointment was booked with.
Numbers are compared by their last :data:`PHONE_KEY_DIGITS` digits, so the
ways a caller says the same number all match: ``+353 87 123 4567``,
``087 123 4567``, ``00353871234567``. Eight digits drop any country code or
trunk ``0`` and keep the rest: an Irish mobile's network digit, and the
whole national number of a Dublin landline (``01 234 5678`` and
``+353 1 234 5678``). Numbers shorter than that must agree in full.

Which number is used is decided by :func:`caller_lookup`: the number the
call comes from (the platform's call record) when there is one, and a
number the caller says only together with the name the booking was made
under, so knowing someone's number alone never reveals their appointments.
"""

from __future__ import annotations

import re
import string
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from fallcha_tools.providers.google_calendar.errors import BadArgumentError

__all__ = [
    "CALLER_PREFIX",
    "MIN_PHONE_DIGITS",
    "NEED_NAME",
    "NEED_PHONE",
    "PHONE_KEY_DIGITS",
    "PHONE_KEY_PROPERTY",
    "PHONE_PREFIX",
    "PHONE_TOO_SHORT",
    "REASON_PREFIX",
    "BookedCaller",
    "CallerLookup",
    "booked_caller",
    "booked_phone_key",
    "caller_lookup",
    "name_matches",
    "one_line",
    "phone_key",
    "private_properties",
]

PHONE_KEY_DIGITS = 8
# Fewer digits than this is not a whole phone number (a lookup is refused).
MIN_PHONE_DIGITS = 7
# Private extended property holding a booking's phone key, so a lookup can
# filter on it at Google. The length is in the name: changing the key length
# needs a new property, never a reinterpretation of stored values.
PHONE_KEY_PROPERTY = f"fallcha_phone_last{PHONE_KEY_DIGITS}"

# How a booking's description names the caller (see CalendarService._event).
CALLER_PREFIX = "Caller: "
PHONE_PREFIX = "Phone: "
REASON_PREFIX = "Reason: "

PHONE_TOO_SHORT = (
    f"caller_phone needs at least {MIN_PHONE_DIGITS} digits; ask for the full "
    "number the appointment was booked with"
)
NEED_PHONE = (
    "the number this call comes from is not known: ask for the phone number "
    "the appointment was booked with and the name it was booked under, then "
    "call again with caller_phone and caller_name"
)
NEED_NAME = (
    "a number other than the one this call comes from needs the name too: ask "
    "for the name the appointment was booked under and call again with "
    "caller_name as well"
)

_WORD = re.compile(r"[^\W\d_]{2,}")


@dataclass(frozen=True, slots=True)
class CallerLookup:
    """Whose bookings to return: ``phone_key`` must match, and every word of
    ``name`` (if any) must be in the booked name."""

    phone_key: str
    name: str | None


@dataclass(frozen=True, slots=True)
class BookedCaller:
    """The caller details a booking was made with."""

    name: str
    phone: str
    reason: str | None


def phone_key(phone: str) -> str | None:
    """The comparable tail of ``phone``; None if it has too few digits."""
    digits = "".join(ch for ch in phone if ch in string.digits)
    if len(digits) < MIN_PHONE_DIGITS:
        return None
    return digits[-PHONE_KEY_DIGITS:]


def caller_lookup(
    *,
    contact_phone: str | None,
    caller_phone: str | None,
    caller_name: str | None,
) -> CallerLookup:
    """The lookup a caller is entitled to.

    ``contact_phone`` is the number the call comes from (None if hidden or
    unknown); ``caller_phone`` and ``caller_name`` are what the caller said.
    The call's own number needs nothing else (a name only narrows the
    result). Any other number needs the booked name as well.
    """
    calling = phone_key(contact_phone) if contact_phone else None
    spoken = _spoken_key(caller_phone)
    name = (caller_name or "").strip() or None
    if calling is not None and spoken in (None, calling):
        return CallerLookup(phone_key=calling, name=name)
    if spoken is None:
        raise BadArgumentError(NEED_PHONE)
    if name is None or not _words(name):
        raise BadArgumentError(NEED_NAME)
    return CallerLookup(phone_key=spoken, name=name)


def _spoken_key(phone: str | None) -> str | None:
    if phone is None or not phone.strip():
        return None
    key = phone_key(phone)
    if key is None:
        raise BadArgumentError(PHONE_TOO_SHORT)
    return key


def private_properties(event: Mapping[str, object]) -> Mapping[str, object]:
    """The event's private extended properties (empty if it has none)."""
    props = event.get("extendedProperties")
    private = props.get("private") if isinstance(props, dict) else None
    return private if isinstance(private, dict) else {}


def booked_phone_key(event: Mapping[str, object]) -> str | None:
    """The phone key a booking was made with.

    Bookings carry it as a private property; older ones only have the
    ``Phone:`` line of their description.
    """
    stored = private_properties(event).get(PHONE_KEY_PROPERTY)
    if isinstance(stored, str):
        return stored
    phone = _description_field(event, PHONE_PREFIX)
    return phone_key(phone) if phone else None


def booked_caller(event: Mapping[str, object]) -> BookedCaller | None:
    """The caller's name, phone and reason from the booking's description;
    None if staff edited away the name or phone."""
    name = _description_field(event, CALLER_PREFIX)
    phone = _description_field(event, PHONE_PREFIX)
    if not name or not phone:
        return None
    reason = _description_field(event, REASON_PREFIX)
    return BookedCaller(name=name, phone=phone, reason=reason or None)


def name_matches(wanted: str, event: Mapping[str, object]) -> bool:
    """Whether every word of ``wanted`` is in the booking's caller name,
    ignoring case and accents ("jane" and "Doe" match "Jane Doe", "Sean"
    matches "Seán"). A name with no words filters nothing."""
    words = _words(wanted)
    if not words:
        return True
    return words <= _words(_description_field(event, CALLER_PREFIX) or "")


def one_line(text: str) -> str:
    """``text`` with every run of whitespace (newlines too) as one space, so
    a caller's words can never add a line to a booking's description."""
    return " ".join(text.split())


def _description_field(event: Mapping[str, object], prefix: str) -> str | None:
    """The value of the description's first line starting with ``prefix``."""
    description = event.get("description")
    if not isinstance(description, str):
        return None
    for line in description.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    return None


def _words(text: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return set(_WORD.findall(plain))
