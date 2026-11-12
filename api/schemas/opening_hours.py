"""When the business is open: an agent's structured opening hours.

Per weekday (Monday first) the day is closed or has one or more open
ranges, e.g. 12:00–15:00 and 17:00–22:00 for split lunch and dinner. A
range whose closing time is at or before its opening time runs past
midnight into the next day (18:00–02:00); "00:00" closes at midnight.
00:00–00:00 is open all day.

Times are wall-clock times in ``timezone`` (default Europe/Dublin), so
daylight saving changes never move them.
"""

from __future__ import annotations

import re
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.schemas.appointment_hours import DEFAULT_TIMEZONE, _iana_zones

MAX_RANGES_PER_DAY = 4
MAX_NOTE_LENGTH = 200
_CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
DAY_MINUTES = 24 * 60


def clock_minutes(value: str) -> int:
    """ "17:30" → 1050."""
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


class OpenRange(BaseModel):
    """One stretch the business is open, as "HH:MM" wall-clock times."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    open: str = Field(description='Opening time, "HH:MM" (24-hour).')
    close: str = Field(
        description='Closing time, "HH:MM". At or before the opening time it '
        'is on the next day ("00:00" is midnight).'
    )

    @field_validator("open", "close")
    @classmethod
    def _clock(cls, value: str) -> str:
        if not _CLOCK.match(value):
            raise ValueError(f"{value!r} is not a time like 09:00 or 17:30")
        return value

    @property
    def start(self) -> int:
        """Minutes after the day's midnight."""
        return clock_minutes(self.open)

    @property
    def end(self) -> int:
        """Minutes after the opening day's midnight, past 1440 when the
        range runs into the next day."""
        close = clock_minutes(self.close)
        return close if close > self.start else close + DAY_MINUTES

    @property
    def overnight(self) -> bool:
        return self.end > DAY_MINUTES


class OpeningHours(BaseModel):
    """The week's opening hours, the business's time zone, and whether
    calls are passed to a person only while it is open."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    days: tuple[
        tuple[OpenRange, ...],
        tuple[OpenRange, ...],
        tuple[OpenRange, ...],
        tuple[OpenRange, ...],
        tuple[OpenRange, ...],
        tuple[OpenRange, ...],
        tuple[OpenRange, ...],
    ] = Field(
        description="Open ranges per weekday, Monday first; an empty day is closed."
    )
    timezone: str = Field(
        default=DEFAULT_TIMEZONE,
        min_length=1,
        max_length=64,
        description="IANA time zone of the business, e.g. Europe/Dublin.",
    )
    transfer_only_when_open: bool = Field(
        default=True,
        description="Pass calls to a person only during opening hours; "
        "outside them the agent takes a message.",
    )
    note: str | None = Field(
        default=None,
        max_length=MAX_NOTE_LENGTH,
        description='Said after the hours, e.g. "Closed on bank holidays."',
    )

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        if value not in _iana_zones():
            raise ValueError(f"Unknown time zone {value!r}")
        return value

    @field_validator("note")
    @classmethod
    def _plain_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        # One line of plain text: it is read out, and must not open a
        # prompt placeholder of its own.
        value = " ".join(value.split())
        value = re.sub(r"\}\}+", "}", re.sub(r"\{\{+", "{", value))
        return value or None

    @model_validator(mode="after")
    def _ranges_in_order(self) -> Self:
        for ranges in self.days:
            if len(ranges) > MAX_RANGES_PER_DAY:
                raise ValueError(
                    f"At most {MAX_RANGES_PER_DAY} opening times on one day"
                )
            previous_end = -1
            for index, open_range in enumerate(ranges):
                if open_range.start <= previous_end:
                    raise ValueError(
                        "A day's opening times must be in order and not overlap"
                    )
                if open_range.overnight and index != len(ranges) - 1:
                    raise ValueError(
                        "Only a day's last opening time can run past midnight"
                    )
                previous_end = open_range.end
        return self
