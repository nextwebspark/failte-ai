"""Which bookings belong to a caller: pure matching rules, no I/O.

A caller is identified by the phone number the appointment was booked with
**and** the name it was booked under; both are always needed.

The number is either the one the call comes from (the platform's call
record, so the caller is not asked for it) or one the caller says. Caller ID
can be spoofed, which is why it only saves asking for the number: without
the booked name it reveals and changes nothing.

Numbers are first compared by their last :data:`PHONE_KEY_DIGITS` digits,
so the ways a caller says the same number all match (``+353 87 123 4567``,
``087 123 4567``, ``00353871234567``); Google filters on that key. Different
numbers can share a key (Dublin ``01 412 3456`` and Cork ``021 412 3456``),
so when both numbers parse they must also be equal in E.164, with the
calendar's region for numbers said without a country code. Numbers shorter
than the key must agree in full.
"""

from __future__ import annotations

import re
import string
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from fallcha_tools.providers.google_calendar.errors import BadArgumentError
from fallcha_tools.providers.google_calendar.phone_numbers import same_number

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
    "phone_matches",
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
_OUR_PREFIXES = (CALLER_PREFIX, PHONE_PREFIX, REASON_PREFIX)

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
    "the name is needed: ask for the name the appointment was booked under "
    "and call again with caller_name"
)

_WORD = re.compile(r"[^\W\d_]{2,}")
# Removed before splitting into words, so O'Brien is one word.
_APOSTROPHES = str.maketrans("", "", "'\u2019\u02bc")


@dataclass(frozen=True, slots=True)
class CallerLookup:
    """Whose bookings to return: booked with ``phone`` (see
    :func:`phone_matches`) under ``name`` (see :func:`name_matches`)."""

    phone: str
    phone_key: str
    name: str


@dataclass(frozen=True, slots=True)
class BookedCaller:
    """The caller details a booking was made with, plus any lines staff
    added to its description."""

    name: str
    phone: str
    reason: str | None
    notes: tuple[str, ...] = ()


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
    The number is the call's own unless the caller says another one; the
    name is always required.
    """
    calling = phone_key(contact_phone) if contact_phone else None
    spoken = _spoken_key(caller_phone)
    if contact_phone and calling is not None and spoken in (None, calling):
        phone, key = contact_phone, calling
    elif caller_phone and spoken is not None:
        phone, key = caller_phone, spoken
    else:
        raise BadArgumentError(NEED_PHONE)
    name = (caller_name or "").strip()
    if not _word_list(name):
        raise BadArgumentError(NEED_NAME)
    return CallerLookup(phone=phone, phone_key=key, name=name)


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


def phone_matches(
    event: Mapping[str, object], lookup: CallerLookup, region: str | None
) -> bool:
    """Whether the booking was made with ``lookup.phone``: the keys agree
    and, when both numbers parse, so do their E.164 forms."""
    if booked_phone_key(event) != lookup.phone_key:
        return False
    booked = _description_field(event, PHONE_PREFIX)
    if not booked:
        return True
    return same_number(booked, lookup.phone, region) is not False


def booked_caller(event: Mapping[str, object]) -> BookedCaller | None:
    """The caller's name, phone, reason and staff notes from the booking's
    description; None if staff edited away the name or phone."""
    name = _description_field(event, CALLER_PREFIX)
    phone = _description_field(event, PHONE_PREFIX)
    if not name or not phone:
        return None
    reason = _description_field(event, REASON_PREFIX)
    return BookedCaller(
        name=name, phone=phone, reason=reason or None, notes=_staff_notes(event)
    )


def name_matches(wanted: str, event: Mapping[str, object]) -> bool:
    """Whether ``wanted`` names the booking's caller, ignoring case, accents
    and apostrophes ("Sean OBrien" matches "Seán O'Brien").

    Every word given must be a booked word or booked words run together
    ("Marykate" for "Mary-Kate", "MacCarthy" for "Mac Carthy"), and when the
    booked name has two or more words the surname (its last word) must be
    among them: "Souza" or "Maria Souza" match "Maria de Souza", "Maria" or
    "de" alone do not. The whole name run together also matches ("Mary Kate
    Doe" for "Marykate Doe"). A name with no words matches nothing.
    """
    words = _word_list(wanted)
    booked = _word_list(_description_field(event, CALLER_PREFIX) or "")
    if not words or not booked:
        return False
    if "".join(words) == "".join(booked):
        return True
    forms = _booked_forms(booked)
    surnames = {form for form, ends_with_surname in forms.items() if ends_with_surname}
    return set(words) <= forms.keys() and (
        len(booked) == 1 or not surnames.isdisjoint(words)
    )


def _booked_forms(booked: list[str]) -> dict[str, bool]:
    """Each booked word and each run of adjacent booked words joined, mapped
    to whether it ends with the last word (the surname)."""
    last = len(booked)
    forms: dict[str, bool] = {}
    for start in range(last):
        for end in range(start + 1, last + 1):
            form = "".join(booked[start:end])
            forms[form] = forms.get(form, False) or end == last
    return forms


def one_line(text: str) -> str:
    """``text`` with every run of whitespace (newlines too) as one space, so
    a caller's words can never add a line to a booking's description."""
    return " ".join(text.split())


def _staff_notes(event: Mapping[str, object]) -> tuple[str, ...]:
    """Description lines after the first (the booked-by line) that are not
    the caller's details: what staff added to the booking."""
    description = event.get("description")
    if not isinstance(description, str):
        return ()
    return tuple(
        line
        for line in description.splitlines()[1:]
        if line.strip() and not line.startswith(_OUR_PREFIXES)
    )


def _description_field(event: Mapping[str, object], prefix: str) -> str | None:
    """The value of the description's first line starting with ``prefix``."""
    description = event.get("description")
    if not isinstance(description, str):
        return None
    for line in description.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    return None


def _word_list(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return _WORD.findall(plain.translate(_APOSTROPHES))
