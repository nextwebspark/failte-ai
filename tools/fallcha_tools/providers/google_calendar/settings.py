"""Per-connection settings (stored in ``connections.config``). The
service-account key format lives in ``google_common``."""

from __future__ import annotations

from typing import Annotated, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fallcha_tools.providers.google_common.service_account import ServiceAccountKey

__all__ = ["CalendarConfig", "ServiceAccountKey", "Weekday"]

Weekday = Annotated[int, Field(ge=0, le=6)]


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
        default="Fallcha.ai call",
        max_length=200,
        description="Event title prefix; the caller's name is appended.",
    )
    booked_by_line: str = Field(
        default="Booked by the Fallcha.ai voice agent.",
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
        return self

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)
