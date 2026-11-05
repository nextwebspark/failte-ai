"""Per-connection settings (stored in ``connections.config``). The
service-account key format lives in ``google_common``."""

from __future__ import annotations

import re
from datetime import time
from typing import Annotated, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fallcha_tools.providers.google_common.service_account import ServiceAccountKey

__all__ = ["CalendarConfig", "ServiceAccountKey", "ServicePeriod", "Weekday"]

# Order-lookup settings that lived here before it moved to Google Sheets.
RETIRED_KEYS = frozenset({"orders_sheet_id", "orders_tab"})

Weekday = Annotated[int, Field(ge=0, le=6)]
_CLOCK_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
# Most bookings any one slot may hold, whatever an owner types: a typo
# (5000 tables) must not let the agent sell an hour without limit.
MAX_CAPACITY = 500
MAX_PARTY = 100


def _clock(value: str) -> time:
    match = _CLOCK_RE.match(value.strip())
    if not match:
        raise ValueError(f"{value!r} is not a time like 17:30")
    return time(int(match.group(1)), int(match.group(2)))


class ServicePeriod(BaseModel):
    """One stretch of the week when bookings may start, e.g. dinner on
    Thursday to Saturday from 17:00, last table at 21:00."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    days: tuple[Weekday, ...] = Field(
        min_length=1, description="Weekdays (Monday=0 ... Sunday=6)."
    )
    first_start: str = Field(
        description="Earliest booking start, 24-hour HH:MM (e.g. 12:00)."
    )
    last_start: str = Field(
        description="Latest booking start, 24-hour HH:MM (e.g. 21:00 for a last "
        "table at nine)."
    )

    @field_validator("first_start", "last_start")
    @classmethod
    def _valid_clock(cls, value: str) -> str:
        return _clock(value).strftime("%H:%M")

    @field_validator("days")
    @classmethod
    def _sorted_days(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        return tuple(sorted(set(value)))

    @model_validator(mode="after")
    def _order(self) -> Self:
        if self.first > self.last:
            raise ValueError("first_start must not be after last_start")
        return self

    @property
    def first(self) -> time:
        return _clock(self.first_start)

    @property
    def last(self) -> time:
        return _clock(self.last_start)


class CalendarConfig(BaseModel):
    """Booking rules for one connection. Defaults match the original shim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    calendar_id: str = Field(
        min_length=1,
        max_length=1024,
        description="Google Calendar id, e.g. abc@group.calendar.google.com.",
    )
    timezone: str = Field(
        default="Europe/Dublin", description="IANA time zone of the business."
    )
    event_summary_prefix: str = Field(
        default="LightMove.ai call",
        max_length=200,
        description="Event title prefix; the caller's name is appended.",
    )
    booked_by_line: str = Field(
        default="Booked by the LightMove.ai voice agent.",
        max_length=200,
        description="First line of the event description.",
    )
    booking_days: tuple[Weekday, ...] = Field(
        default=(0, 1, 2, 3, 4),
        min_length=1,
        description="Weekdays bookings are offered on (Monday=0 ... Sunday=6).",
    )
    open_hour: int = Field(default=9, ge=0, le=23)
    close_hour: int = Field(
        default=17, ge=1, le=24, description="Last slot ends by this hour."
    )
    slot_minutes: int = Field(default=30, ge=5, le=240)
    buffer_minutes: int = Field(default=15, ge=0, le=240)
    min_lead_hours: int = Field(default=2, ge=0, le=168)
    horizon_days: int = Field(default=14, ge=1, le=60)
    max_slots_returned: int = Field(default=3, ge=1, le=10)
    morning_end_hour: int = Field(default=12, ge=0, le=24)
    # Booking rules (see the README's "Booking rules"). The defaults keep a
    # plain appointment diary: one booking at a time, no party size.
    ai_booking_enabled: bool = Field(
        default=True,
        description="Off: the agent offers no times and books nothing; it takes "
        "the caller's details for the team instead.",
    )
    service_periods: tuple[ServicePeriod, ...] = Field(
        default=(),
        max_length=21,
        description="When bookings may start, per weekday, e.g. lunch and dinner. "
        "Set, it replaces booking_days, open_hour and close_hour.",
    )
    booking_minutes: int | None = Field(
        default=None,
        ge=5,
        le=720,
        description="How long one booking holds a table or a slot (e.g. 90 for a "
        "dinner table). Empty: slot_minutes.",
    )
    max_bookings_at_once: int = Field(
        default=1,
        ge=1,
        le=MAX_CAPACITY,
        description="Bookings the agent may hold at the same time, e.g. the "
        "number of tables you release for phone bookings. 1 for a one-person "
        "diary.",
    )
    max_guests_at_once: int | None = Field(
        default=None,
        ge=1,
        le=MAX_CAPACITY * 20,
        description="Most guests (covers) seated at the same time from agent "
        "bookings. Empty: no limit beyond max_bookings_at_once.",
    )
    max_guests_per_start: int | None = Field(
        default=None,
        ge=1,
        le=MAX_CAPACITY * 20,
        description="Most guests arriving at the same start time (kitchen "
        "pacing). Empty: no limit.",
    )
    ask_party_size: bool = Field(
        default=False,
        description="The agent must ask how many people before booking. Always "
        "on when a guest limit or max_party_size is set.",
    )
    min_party_size: int = Field(default=1, ge=1, le=MAX_PARTY)
    max_party_size: int | None = Field(
        default=None,
        ge=1,
        le=MAX_PARTY,
        description="Largest party the agent may book. Bigger groups are passed "
        "to your team.",
    )
    party_summary: str = Field(
        default="Table for {n}",
        max_length=60,
        description="Event title start when a party size is given; {n} is the "
        "number of people.",
    )

    @model_validator(mode="before")
    @classmethod
    def _drop_retired_keys(cls, data: object) -> object:
        # Order lookup moved to Google Sheets; configs saved before that
        # still carry its keys and must keep validating.
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if k not in RETIRED_KEYS}
        return data

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown time zone {value!r}") from None
        return value

    @field_validator("booking_days")
    @classmethod
    def _sorted_days(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        return tuple(sorted(set(value)))

    @model_validator(mode="after")
    def _hours_order(self) -> Self:
        if self.open_hour >= self.close_hour:
            raise ValueError("open_hour must be before close_hour")
        if (self.close_hour - self.open_hour) * 60 < self.slot_minutes:
            raise ValueError("opening hours are shorter than one slot")
        if (
            self.max_party_size is not None
            and self.max_party_size < self.min_party_size
        ):
            raise ValueError("max_party_size must not be below min_party_size")
        if (
            self.max_party_size is not None
            and self.max_guests_at_once is not None
            and self.max_party_size > self.max_guests_at_once
        ):
            raise ValueError("max_party_size must not be above max_guests_at_once")
        return self

    @property
    def booking_length(self) -> int:
        """Minutes one booking holds capacity."""
        return self.booking_minutes or self.slot_minutes

    @property
    def counts_capacity(self) -> bool:
        """Several bookings may share a time (tables, chairs, rooms): bookings
        are counted from the calendar's events rather than free/busy."""
        return (
            self.max_bookings_at_once > 1
            or self.max_guests_at_once is not None
            or self.max_guests_per_start is not None
        )

    @property
    def needs_party_size(self) -> bool:
        return (
            self.ask_party_size
            or self.max_party_size is not None
            or self.max_guests_at_once is not None
            or self.max_guests_per_start is not None
        )

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)
