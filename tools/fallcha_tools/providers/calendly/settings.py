"""Per-connection settings (stored in ``connections.config``) and the token
format of a Calendly connection."""

from __future__ import annotations

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import phonenumbers
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

API_BASE = "https://api.calendly.com"
# Event types are addressed by URI. Only Calendly's own API host is ever
# called with the connection's token, so the URI must be on it.
EVENT_TYPE_URI = re.compile(
    r"^https://api\.calendly\.com/event_types/([A-Za-z0-9-]{1,64})$"
)
# Marks the config fields the admin picks from a live list (``choices``)
# rather than types: the picked value and its display name. The UI's generic
# settings form leaves them out and shows a picker instead.
CHOICE_VALUE: dict[str, JsonValue] = {"x-fallcha-choice": "value"}
CHOICE_LABEL: dict[str, JsonValue] = {"x-fallcha-choice": "label"}
MAX_HORIZON_DAYS = 60


def event_type_uuid(uri: str) -> str:
    match = EVENT_TYPE_URI.fullmatch(uri)
    if not match:
        raise ValueError("not a Calendly event type address")
    return match.group(1)


class CalendlyToken(BaseModel):
    """The secret of an ``api_key`` connection: a personal access token."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=4096, pattern=r"^\S+$")


class CalendlyConfig(BaseModel):
    """Which Calendly event callers book, and how times are offered."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: str | None = Field(
        default=None,
        description="The Calendly event type callers are booked into.",
        json_schema_extra=CHOICE_VALUE,
    )
    event_type_name: str | None = Field(
        default=None,
        max_length=200,
        description="Its name, as Calendly shows it.",
        json_schema_extra=CHOICE_LABEL,
    )
    timezone: str | None = Field(
        default=None,
        description="Time zone used to say times to callers, e.g. Europe/Dublin. "
        "Empty: your Calendly account's time zone.",
    )
    ai_booking_enabled: bool = Field(
        default=True,
        description="Off: the agent offers no times and books nothing; it takes "
        "the caller's details for the team instead.",
    )
    horizon_days: int = Field(
        default=14,
        ge=1,
        le=MAX_HORIZON_DAYS,
        description="How many days ahead the agent looks for free times.",
    )
    max_slots_returned: int = Field(
        default=3,
        ge=1,
        le=10,
        description="How many free times the agent offers at once.",
    )
    phone_region: str | None = Field(
        default=None,
        min_length=2,
        max_length=2,
        description="Country (e.g. IE) for phone numbers said without a "
        "country code. Empty: the country of the time zone.",
    )

    @field_validator("event_type")
    @classmethod
    def _calendly_uri(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        event_type_uuid(value)
        return value

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
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

    @property
    def min_lead_hours(self) -> int:
        """Calendly applies the event type's own minimum notice."""
        return 0
