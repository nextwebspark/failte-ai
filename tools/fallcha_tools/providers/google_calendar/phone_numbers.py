"""Full phone-number comparison (E.164) and a calendar's default region.

A number said in national form (``087 123 4567``) only has a country once a
region is known: the connection's ``phone_region``, else the country of its
time zone. A zone ``zone.tab`` lists gives its country. Any other name
(``Asia/Calcutta``, ``US/Eastern``) is followed through the ``L target link``
lines of ``tzdata.zi`` and counts only if ``zone1970.tab`` gives the target
exactly one country: many legacy names link to a zone several countries
share (``Iceland`` to Africa/Abidjan). Rule zones (``CET``, ``EST5EDT``)
name no country. The ``tzdata`` package is read first (so the base image
does not matter), then the system's ``zoneinfo.TZPATH``.
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
# Zones named after a rule, not a place (some are links to a city zone since
# tzdata 2024b: CET to Europe/Brussels), so they name no country.
RULE_ZONES = frozenset(
    {
        "CET",
        "MET",
        "EET",
        "WET",
        "EST",
        "MST",
        "HST",
        "EST5EDT",
        "CST6CDT",
        "MST7MDT",
        "PST8PDT",
    }
)


@dataclass(frozen=True, slots=True)
class _TimeZoneTable:
    countries: Mapping[str, str]  # zone.tab: zone -> its one country
    shared: Mapping[str, tuple[str, ...]]  # zone1970.tab: zone -> countries
    links: Mapping[str, str]  # tzdata.zi: legacy name -> target

    def country(self, timezone: str) -> str | None:
        """The country of a zone listed in zone.tab. A legacy name counts
        only if its target serves a single country (zone1970.tab): since
        tzdata 2022b many link across countries (Iceland to Africa/Abidjan,
        Atlantic/Jan_Mayen to Europe/Berlin)."""
        if timezone in RULE_ZONES:
            return None
        if timezone in self.countries:
            return self.countries[timezone]
        zone = timezone
        for _ in range(MAX_LINK_HOPS):
            target = self.links.get(zone)
            if target is None:
                break
            zone = target
        if zone == timezone:
            return None
        served = self.shared.get(zone, ())
        return served[0] if len(served) == 1 else None


@functools.cache
def region_for_timezone(timezone: str) -> str | None:
    """The ISO 3166 country of an IANA time zone, legacy names included
    (``Europe/Dublin`` and ``Eire`` are ``IE``); None if it names no single
    country or no time-zone table can be read. Warns once per zone."""
    table = _time_zone_table()
    region = table.country(timezone) if table is not None else None
    if region is None and table is not None:
        logger.warning(
            "time zone {} names no single country; national phone numbers are "
            "matched on their last digits only unless phone_region is set",
            timezone,
        )
    return region


@functools.cache
def _time_zone_table() -> _TimeZoneTable | None:
    """The first readable database. A database is used whole, never mixed
    with another: with the ``tzdata>=2026.4`` floor the package's is the one
    in use, and the system's is only a fallback."""
    for directory in _tzdb_directories():
        if not (directory / "zone.tab").is_file():
            continue
        try:
            return _TimeZoneTable(
                countries=_zone_tab(_read(directory, "zone.tab")),
                shared=_zone1970_tab(_read(directory, "zone1970.tab")),
                links=_links(_read(directory, "tzdata.zi")),
            )
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("time-zone database unreadable: {}", type(exc).__name__)
            return None
    logger.warning(
        "no zone.tab found; set phone_region on calendar connections so national "
        "phone numbers are compared in full"
    )
    return None


def _read(directory: Traversable, name: str) -> str:
    """A database file's text; empty if this database lacks it."""
    path = directory / name
    return path.read_text(encoding="utf-8") if path.is_file() else ""


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


def _zone1970_tab(text: str) -> dict[str, tuple[str, ...]]:
    """Zone name -> the countries it serves, from ``zone1970.tab``
    (``CI,BF,GH  +0519-00402  Africa/Abidjan``)."""
    zones: dict[str, tuple[str, ...]] = {}
    for line in text.splitlines():
        fields = line.split("\t")
        if line.startswith("#") or len(fields) < 3:
            continue
        zones[fields[2]] = tuple(fields[0].split(","))
    return zones


def _links(text: str) -> dict[str, str]:
    """Legacy name -> target from ``tzdata.zi``'s ``L target link`` lines."""
    links: dict[str, str] = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[0] == "L":
            links[fields[2]] = fields[1]
    return links
