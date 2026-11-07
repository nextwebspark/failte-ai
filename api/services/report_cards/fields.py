"""Reading the details an agent wrote down on a call (``gathered_context``).

The agent writes what the caller said, so the text is loose ("4", "four",
"4 people", "a table for two"). These read it strictly: anything that
can't be read for sure is reported as unreadable, never guessed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, time
from typing import Any

# The largest party a phone booking can sensibly be for.
MAX_PARTY = 200

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
}


def text(gathered: Mapping[str, Any] | None, key: str) -> str | None:
    value = (gathered or {}).get(key)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def party_size(value: Any) -> int | None:
    """How many people a booking is for: "4", "4 people", "four", "a table
    for two". None when there is no single clear number (empty, "4 or 5",
    "a couple", "lots")."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if not value.is_integer():
            return None
        number = int(value)
    elif isinstance(value, str):
        lowered = value.strip().lower()
        digits = re.findall(r"\d+(?:\.\d+)?", lowered)
        words = [
            _NUMBER_WORDS[w]
            for w in re.findall(r"[a-z]+", lowered)
            if w in _NUMBER_WORDS
        ]
        found = [float(d) for d in digits] + [float(w) for w in words]
        if len(found) != 1 or not found[0].is_integer():
            return None
        number = int(found[0])
    else:
        return None
    return number if 1 <= number <= MAX_PARTY else None


def booking_day(value: Any) -> date | None:
    """The ISO day a booking is for ("2026-11-14"); None when not a date."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def booking_clock(value: Any) -> time | None:
    """The time a booking is for ("19:30"); None when unreadable."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", value)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


# An Irish Eircode: routing key (letter, two digits; or D6W) and four more.
_EIRCODE = re.compile(r"\b(?:[ac-fhknprtv-y]\d{2}|d6w)\s?[0-9ac-fhknprtv-y]{4}\b", re.I)
_COUNTY = re.compile(r"^(?:co\.?|county)\s+(.+)$", re.I)
_DUBLIN_DISTRICT = re.compile(r"^dublin\s+\d{1,2}w?$", re.I)
_COUNTRY = {"ireland", "eire", "éire", "republic of ireland", "roi"}

# What ``area`` returns for an address it can't place.
UNCLEAR = "__unclear__"


def _title(value: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in value.split())


def area(address: Any) -> str | None:
    """The town (or, with only a county, the county) a job address is in:
    the last part of the address that is a place name. "15 Riverside Park,
    Douglas" → "Douglas"; "Main St, Midleton, Co. Cork" → "Midleton";
    "Co. Cork" → "Co. Cork"; "Dublin 12" stays. None for no address,
    ``UNCLEAR`` when no part reads as a place (a lone street, a house
    number, a long sentence)."""
    raw = text({"a": address}, "a")
    if raw is None:
        return None
    cleaned = _EIRCODE.sub(" ", raw)
    parts = [
        p.strip(" .-")
        for p in re.split(r"[,\n;]+", cleaned)
        if p.strip(" .-") and p.strip(" .-").lower() not in _COUNTRY
    ]
    if not parts:
        return UNCLEAR
    county: str | None = None
    places: list[str] = []
    for part in parts:
        found = _COUNTY.match(part)
        if found:
            county = f"Co. {_title(found.group(1).strip())}"
            continue
        if _DUBLIN_DISTRICT.match(part):
            places.append(_title(part.lower()))
            continue
        if any(ch.isdigit() for ch in part):
            continue
        places.append(part)
    # One part only: a street or a sentence, unless it is short and plain.
    if len(parts) == 1 and places:
        only = places[0]
        if len(only.split()) > 3 or re.search(
            r"\b(?:road|rd|street|st|avenue|ave|park|drive|lane|grove|close|court|way|terrace)\b",
            only,
            re.I,
        ):
            return county or UNCLEAR
        return _title(only)
    if places and len(parts) > 1:
        last = places[-1]
        if len(last.split()) <= 3:
            return _title(last)
    return county or UNCLEAR


def question_key(question: str) -> str:
    """Two phrasings of one question group together: case, punctuation and
    spacing don't count."""
    words = re.findall(r"[a-z0-9]+", question.casefold())
    return " ".join(words)


def is_emergency(value: Any) -> bool:
    """The trades agent's ``urgency``: "emergency" (or "an emergency")."""
    found = text({"a": value}, "a")
    return bool(found and "emergenc" in found.lower())
