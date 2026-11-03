"""When callers can book appointments: a template's structured setup answer.

The limits match the Google Calendar connection's booking settings
(``tools/fallcha_tools/providers/google_calendar/settings.py``), so hours
accepted here can be saved to that connection unchanged.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum
from functools import cache
from typing import Self
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_TIMEZONE = "Europe/Dublin"


@cache
def _iana_zones() -> frozenset[str]:
    # Scans the tz database on disk, so only once.
    return frozenset(available_timezones())


class Weekday(IntEnum):
    """Day of the week, Monday=0 ... Sunday=6 (Python's ``date.weekday()``)."""

    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


WORKING_WEEK: tuple[Weekday, ...] = (
    Weekday.MONDAY,
    Weekday.TUESDAY,
    Weekday.WEDNESDAY,
    Weekday.THURSDAY,
    Weekday.FRIDAY,
)


class AppointmentHours(BaseModel):
    """The days, hours, length and time zone of bookable appointments. One
    window for all booking days, in whole hours."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    booking_days: tuple[Weekday, ...] = Field(
        default=WORKING_WEEK,
        min_length=1,
        description="Weekdays appointments can be booked on (Monday=0 ... Sunday=6).",
    )
    open_hour: int = Field(
        default=9, ge=0, le=23, description="First appointment starts at this hour."
    )
    close_hour: int = Field(
        default=17, ge=1, le=24, description="Last appointment ends by this hour."
    )
    slot_minutes: int = Field(
        default=30, ge=5, le=240, description="Length of one appointment."
    )
    timezone: str = Field(
        default=DEFAULT_TIMEZONE,
        min_length=1,
        max_length=64,
        description="IANA time zone of the business, e.g. Europe/Dublin.",
    )

    @field_validator("booking_days")
    @classmethod
    def _sorted_days(cls, value: tuple[Weekday, ...]) -> tuple[Weekday, ...]:
        return tuple(sorted(set(value)))

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        # Stricter than ZoneInfo(value), which also opens non-zone files
        # such as "posixrules".
        if value not in _iana_zones():
            raise ValueError(f"Unknown time zone {value!r}")
        return value

    @model_validator(mode="after")
    def _hours_order(self) -> Self:
        if self.open_hour >= self.close_hour:
            raise ValueError("The closing hour must be after the opening hour")
        if (self.close_hour - self.open_hour) * 60 < self.slot_minutes:
            raise ValueError("An appointment is longer than the booking hours")
        return self


class CalendarHoursStatus(StrEnum):
    """What happened to the Google Calendar connection's booking hours when an
    agent was created with appointment hours."""

    UPDATED = "updated"
    # The member's role can't change integration settings.
    NOT_ALLOWED = "not_allowed"
    # The agent was created, but the hours could not be saved.
    FAILED = "failed"
