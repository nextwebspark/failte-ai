"""Pure slot arithmetic, ported from the calendar shim.

The agent prompt is static and has no reliable idea what today is, so the
model passes phrases ("tomorrow", "next tuesday") and this module turns them
into search windows and concrete, opening-hours-aligned slots.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from fallcha_tools.providers.google_calendar.settings import CalendarConfig

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_WEEKDAY_RE = re.compile(r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)")
_ISO_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

Window = tuple[datetime, datetime]
Busy = tuple[datetime, datetime]
# Evening starts here for "evening" requests (restaurants, late clinics).
EVENING_HOUR = 17


@dataclass(frozen=True, slots=True)
class Booked:
    """A booking that takes up capacity: one table or chair, ``guests`` seats."""

    start: datetime
    end: datetime
    guests: int = 1


def _midnight(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


class BookingHorizon(Protocol):
    """How far ahead bookings may be made (shared with other booking
    providers, e.g. Calendly)."""

    @property
    def min_lead_hours(self) -> int: ...
    @property
    def horizon_days(self) -> int: ...


def bookable_window(now: datetime, config: BookingHorizon) -> Window:
    """[earliest bookable moment, horizon) for ``now`` (local time)."""
    return (
        now + timedelta(hours=config.min_lead_hours),
        now + timedelta(days=config.horizon_days),
    )


def resolve_window(
    relative_day: str | None, now: datetime, config: BookingHorizon
) -> Window:
    """Turn a spoken date phrase into a [start, end) search window.

    The window never leaves [earliest, horizon); it may be empty (start >= end).
    """
    earliest, horizon = bookable_window(now, config)
    phrase = (relative_day or "").strip().lower()

    def day_bounds(day: datetime) -> Window:
        # Clamped to what is bookable: a day past the horizon is empty.
        start = _midnight(day)
        return max(start, earliest), min(start + timedelta(days=1), horizon)

    if not phrase or "week" in phrase or "any" in phrase or "soon" in phrase:
        return earliest, horizon
    if "today" in phrase or "tonight" in phrase:
        return day_bounds(now)
    if "tomorrow" in phrase:
        return day_bounds(now + timedelta(days=1))

    weekday = _WEEKDAY_RE.search(phrase)
    if weekday:
        ahead = (WEEKDAYS[weekday.group(1)] - now.weekday()) % 7
        if ahead == 0 or "next" in phrase:
            ahead = ahead or 7
        return day_bounds(now + timedelta(days=ahead))

    iso = _ISO_DATE_RE.search(phrase)
    if iso:
        try:
            day = datetime.fromisoformat(iso.group(1)).replace(tzinfo=now.tzinfo)
        except ValueError:
            return earliest, horizon
        return day_bounds(day)

    return earliest, horizon


def _wanted(slot: datetime, want: str, config: CalendarConfig) -> bool:
    if not want:
        return True
    morning = slot.hour < config.morning_end_hour
    if want.startswith("morning"):
        return morning
    if want.startswith("evening") or want.startswith("night"):
        return slot.hour >= EVENING_HOUR
    if want.startswith("afternoon"):
        return not morning and slot.hour < EVENING_HOUR
    return True


def _day_starts(day: datetime, config: CalendarConfig) -> list[datetime]:
    """Every allowed start on ``day`` (local midnight), in order."""
    step = timedelta(minutes=config.slot_minutes)
    starts: set[datetime] = set()
    if config.service_periods:
        for period in config.service_periods:
            if day.weekday() not in period.days:
                continue
            slot = day.replace(hour=period.first.hour, minute=period.first.minute)
            last = day.replace(hour=period.last.hour, minute=period.last.minute)
            while slot <= last:
                starts.add(slot)
                slot += step
        return sorted(starts)
    if day.weekday() not in config.booking_days:
        return []
    slot = day.replace(hour=config.open_hour)
    last_start = (
        day.replace(hour=config.close_hour)
        if config.close_hour < 24
        else day.replace(hour=23) + timedelta(hours=1)
    ) - step
    while slot <= last_start:
        starts.add(slot)
        slot += step
    return sorted(starts)


def candidate_slots(
    start: datetime, end: datetime, part_of_day: str | None, config: CalendarConfig
) -> Iterator[datetime]:
    """Every slot inside opening hours in [start, end), ignoring the calendar.

    Opening hours are ``service_periods`` when set (each gives the first and
    last start time), else ``booking_days`` from ``open_hour`` with the last
    slot ending by ``close_hour``.
    """
    want = (part_of_day or "").strip().lower()
    day = _midnight(start)
    while day < end:
        for slot in _day_starts(day, config):
            if start <= slot < end and _wanted(slot, want, config):
                yield slot
        day += timedelta(days=1)


def free_slots(
    start: datetime,
    end: datetime,
    part_of_day: str | None,
    limit: int,
    busy: Sequence[Busy],
    config: CalendarConfig,
) -> list[datetime]:
    """Up to ``limit`` candidate slots that keep the buffer from every busy block."""
    buffer = timedelta(minutes=config.buffer_minutes)
    length = timedelta(minutes=config.slot_minutes)
    found: list[datetime] = []
    for slot in candidate_slots(start, end, part_of_day, config):
        slot_end = slot + length
        clash = any(
            slot < block_end + buffer and block_start < slot_end + buffer
            for block_start, block_end in busy
        )
        if not clash:
            found.append(slot)
            if len(found) >= limit:
                break
    return found


def has_room(
    slot: datetime,
    booked: Sequence[Booked],
    blocked: Sequence[Busy],
    config: CalendarConfig,
    party_size: int | None,
) -> bool:
    """Whether one more booking of ``party_size`` fits at ``slot``.

    Each booking holds its capacity for ``booking_length`` minutes plus the
    buffer (the table reset). The check uses the busiest moment of the new
    booking's stay, so a table freed at 18:30 can be sold again at 18:30.
    A blocking event (a closure, a private party) closes the time entirely.
    """
    buffer = timedelta(minutes=config.buffer_minutes)
    slot_end = slot + timedelta(minutes=config.booking_length)
    if any(
        slot < b_end + buffer and b_start < slot_end + buffer
        for b_start, b_end in blocked
    ):
        return False
    party = party_size or 1
    overlapping = [
        b for b in booked if b.start < slot_end + buffer and slot < b.end + buffer
    ]
    moments = {slot} | {b.start for b in overlapping if slot <= b.start}
    peak_bookings = 0
    peak_guests = 0
    for moment in moments:
        here = [b for b in overlapping if b.start <= moment < b.end + buffer]
        peak_bookings = max(peak_bookings, len(here))
        peak_guests = max(peak_guests, sum(b.guests for b in here))
    if peak_bookings + 1 > config.max_bookings_at_once:
        return False
    if (
        config.max_guests_at_once is not None
        and peak_guests + party > config.max_guests_at_once
    ):
        return False
    if config.max_guests_per_start is not None:
        arriving = sum(b.guests for b in booked if b.start == slot)
        if arriving + party > config.max_guests_per_start:
            return False
    return True


def open_slots(
    start: datetime,
    end: datetime,
    part_of_day: str | None,
    limit: int,
    booked: Sequence[Booked],
    blocked: Sequence[Busy],
    config: CalendarConfig,
    party_size: int | None,
) -> list[datetime]:
    """Up to ``limit`` candidate slots with room for one more booking."""
    found: list[datetime] = []
    for slot in candidate_slots(start, end, part_of_day, config):
        if has_room(slot, booked, blocked, config, party_size):
            found.append(slot)
            if len(found) >= limit:
                break
    return found
