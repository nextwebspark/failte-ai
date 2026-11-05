"""Per-connection settings (stored in ``connections.config``). The
service-account key format lives in ``google_common``."""

from __future__ import annotations

from typing import Annotated, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import phonenumbers
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fallcha_tools.providers.google_calendar.phone_numbers import region_for_timezone
from fallcha_tools.providers.google_common.service_account import ServiceAccountKey

__all__ = ["MAX_HORIZON_DAYS", "CalendarConfig", "ServiceAccountKey", "Weekday"]

# Order-lookup settings that lived here before it moved to Google Sheets.
RETIRED_KEYS = frozenset({"orders_sheet_id", "orders_tab"})

Weekday = Annotated[int, Field(ge=0, le=6)]

# Furthest ahead any connection may offer slots, so no booking ever starts
# later than this many days after it was made.
MAX_HORIZON_DAYS = 60


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
    horizon_days: int = Field(default=14, ge=1, le=MAX_HORIZON_DAYS)
    max_slots_returned: int = Field(default=3, ge=1, le=10)
    morning_end_hour: int = Field(default=12, ge=0, le=24)
    phone_region: str | None = Field(
        default=None,
        min_length=2,
        max_length=2,
        description=(
            "ISO 3166 country (e.g. IE) for phone numbers said without a "
            "country code; defaults to the country of the time zone."
        ),
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

    @field_validator("phone_region")
    @classmethod
    def _known_region(cls, value: str | None) -> str | None:
        if value is None:
            return None
        region = value.upper()
        if region not in phonenumbers.SUPPORTED_REGIONS:
            raise ValueError(f"unknown phone region {value!r}")
        return region

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
        return self

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def default_phone_region(self) -> str | None:
        """Region for national-format numbers; None if it cannot be told."""
        return self.phone_region or region_for_timezone(self.timezone)
