"""Pure slot arithmetic, ported from the calendar shim.

The agent prompt is static and has no reliable idea what today is, so the
model passes phrases ("tomorrow", "next tuesday") and this module turns them
into search windows and concrete, opening-hours-aligned slots.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta

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


def _midnight(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def bookable_window(now: datetime, config: CalendarConfig) -> Window:
    """[earliest bookable moment, horizon) for ``now`` (local time)."""
    return (
        now + timedelta(hours=config.min_lead_hours),
        now + timedelta(days=config.horizon_days),
    )


def resolve_window(
    relative_day: str | None, now: datetime, config: CalendarConfig
) -> Window:
    """Turn a spoken date phrase into a [start, end) search window."""
    earliest, horizon = bookable_window(now, config)
    phrase = (relative_day or "").strip().lower()

    def day_bounds(day: datetime) -> Window:
        start = _midnight(day)
        return max(start, earliest), start + timedelta(days=1)

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


def candidate_slots(
    start: datetime, end: datetime, part_of_day: str | None, config: CalendarConfig
) -> Iterator[datetime]:
    """Every slot inside opening hours in [start, end), ignoring the calendar."""
    want = (part_of_day or "").strip().lower()
    day = _midnight(start)
    step = timedelta(minutes=config.slot_minutes)
    while day < end:
        if day.weekday() in config.booking_days:
            slot = day.replace(hour=config.open_hour)
            last_start = (
                day.replace(hour=config.close_hour)
                if config.close_hour < 24
                else day.replace(hour=23) + timedelta(hours=1)
            ) - step
            while slot <= last_start:
                if start <= slot < end:
                    morning = slot.hour < config.morning_end_hour
                    if (
                        not want
                        or (want.startswith("morning") and morning)
                        or (want.startswith("afternoon") and not morning)
                    ):
                        yield slot
                slot += step
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
