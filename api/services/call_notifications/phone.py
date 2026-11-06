"""Turning the numbers a call carries into ones a text can be sent to."""

from __future__ import annotations

import re

DEFAULT_DIAL_CODE = "353"  # Ireland

_SEPARATORS = re.compile(r"[\s\-().]")
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")
# Irish mobiles are 08x; Irish landlines can't receive texts.
_IRISH_MOBILE = re.compile(r"^\+3538[3-9]\d{7}$")


def to_e164(raw: object, default_dial_code: str = DEFAULT_DIAL_CODE) -> str | None:
    """``raw`` as E.164, or None when it isn't a usable phone number.

    "087 123 4567" -> "+353871234567"; "0044 7700 900123" -> "+447700900123";
    "+353 87 123 4567" stays as is; "sip:+353871234567@carrier" gives its
    number. A national number (leading 0) is read as Irish. Withheld numbers
    ("anonymous"), extensions and short codes give None.
    """
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if value.lower().startswith(("sip:", "sips:")):
        # A SIP caller id carries the number as its user part.
        value = value.split(":", 1)[1].split("@", 1)[0].split(";", 1)[0]
    value = _SEPARATORS.sub("", value)
    if value.startswith("00"):
        value = "+" + value[2:]
    elif value.startswith("0"):
        value = f"+{default_dial_code}{value[1:]}"
    elif value.isdigit() and value.startswith(default_dial_code):
        # Some carriers send the full number without the "+".
        value = "+" + value
    return value if _E164.match(value) else None


def can_receive_texts(e164: str) -> bool:
    """False for numbers known not to take texts: Irish landlines. Other
    countries' numbers are tried; the provider reports any it can't reach."""
    if e164.startswith("+353"):
        return bool(_IRISH_MOBILE.match(e164))
    return True


def textable_number(*candidates: object) -> str | None:
    """The first candidate that is a valid number able to receive texts."""
    for candidate in candidates:
        number = to_e164(candidate)
        if number is not None and can_receive_texts(number):
            return number
    return None
