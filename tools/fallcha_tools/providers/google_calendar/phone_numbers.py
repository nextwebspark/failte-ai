"""Full phone-number comparison (E.164) and a calendar's default region.

A number said in national form (``087 123 4567``) only has a country once a
region is known: the connection's ``phone_region``, else the country of its
time zone, read from the system time-zone table (``zone.tab``).
"""

from __future__ import annotations

import functools
import zoneinfo
from pathlib import Path

import phonenumbers

__all__ = ["e164", "region_for_timezone", "same_number"]


def e164(number: str, region: str | None) -> str | None:
    """``number`` as E.164 (``+353871234567``); None if it does not parse
    as a possible number (a national number needs ``region``)."""
    try:
        parsed = phonenumbers.parse(number, region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_possible_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def same_number(first: str, second: str, region: str | None) -> bool | None:
    """Whether two numbers are the same one; None if either does not parse."""
    a, b = e164(first, region), e164(second, region)
    if a is None or b is None:
        return None
    return a == b


@functools.cache
def region_for_timezone(timezone: str) -> str | None:
    """The ISO 3166 country of an IANA time zone (``Europe/Dublin`` is
    ``IE``); None if the system has no ``zone.tab`` or does not list it."""
    for directory in zoneinfo.TZPATH:
        table = Path(directory) / "zone.tab"
        if table.is_file():
            return _zone_tab(table.read_text(encoding="utf-8")).get(timezone)
    return None


def _zone_tab(text: str) -> dict[str, str]:
    """Zone name -> country code from ``zone.tab`` (``IE  +5320-00615
    Europe/Dublin``; ``#`` starts a comment line)."""
    zones: dict[str, str] = {}
    for line in text.splitlines():
        fields = line.split("\t")
        if line.startswith("#") or len(fields) < 3:
            continue
        zones[fields[2]] = fields[0]
    return zones
