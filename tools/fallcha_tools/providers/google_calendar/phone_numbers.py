"""Full phone-number comparison (E.164) and a calendar's default region.

A number said in national form (``087 123 4567``) only has a country once a
region is known: the connection's ``phone_region``, else the country of its
time zone. That comes from the time-zone database's ``zone.tab``, after
legacy names (``Asia/Calcutta``, ``US/Eastern``) are resolved to their
canonical zone through the ``L target link`` lines of ``tzdata.zi``. The
``tzdata`` package is read first (so the base image does not matter), then
the system's ``zoneinfo.TZPATH``.
"""

from __future__ import annotations

import functools
import zoneinfo
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

import phonenumbers
from loguru import logger

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


# A link may point at another link; real chains are one or two long.
MAX_LINK_HOPS = 5


@dataclass(frozen=True, slots=True)
class _TimeZoneTable:
    countries: Mapping[str, str]  # canonical zone -> ISO 3166 country
    links: Mapping[str, str]  # legacy name -> target

    def country(self, timezone: str) -> str | None:
        zone = timezone
        for _ in range(MAX_LINK_HOPS):
            if zone in self.countries:
                return self.countries[zone]
            target = self.links.get(zone)
            if target is None:
                return None
            zone = target
        return None


@functools.cache
def region_for_timezone(timezone: str) -> str | None:
    """The ISO 3166 country of an IANA time zone, legacy names included
    (``Europe/Dublin`` and ``Eire`` are ``IE``); None if it names no country
    or no time-zone table can be read. Warns once per zone."""
    table = _time_zone_table()
    region = table.country(timezone) if table is not None else None
    if region is None and table is not None:
        logger.warning(
            "time zone {} names no country; national phone numbers are matched "
            "on their last digits only unless phone_region is set",
            timezone,
        )
    return region


@functools.cache
def _time_zone_table() -> _TimeZoneTable | None:
    for directory in _tzdb_directories():
        zone_tab = directory / "zone.tab"
        if not zone_tab.is_file():
            continue
        links = directory / "tzdata.zi"
        return _TimeZoneTable(
            countries=_zone_tab(zone_tab.read_text(encoding="utf-8")),
            links=_links(links.read_text(encoding="utf-8")) if links.is_file() else {},
        )
    logger.warning(
        "no zone.tab found; set phone_region on calendar connections so national "
        "phone numbers are compared in full"
    )
    return None


def _tzdb_directories() -> list[Traversable]:
    """The ``tzdata`` package's database first, then the system's."""
    system: list[Traversable] = [Path(directory) for directory in zoneinfo.TZPATH]
    try:
        package = resources.files("tzdata")
    except ModuleNotFoundError:
        return system
    return [package / "zoneinfo", *system]


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


def _links(text: str) -> dict[str, str]:
    """Legacy name -> target from ``tzdata.zi``'s ``L target link`` lines."""
    links: dict[str, str] = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[0] == "L":
            links[fields[2]] = fields[1]
    return links
