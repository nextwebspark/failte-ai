"""Inputs and outputs of the Calendly functions.

The argument types are the Google Calendar ones (same names, same meaning),
so an agent's instructions work with either calendar. Field descriptions are
the agent's function-argument docs, written for an LLM on a phone call.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from fallcha_tools.providers.google_calendar.schemas import (
    CallerName,
    PartOfDay,
    Reason,
    RelativeDay,
    Slot,
    SlotId,
)

__all__ = [
    "AvailabilityResult",
    "Booking",
    "BookingResult",
    "CallerEmail",
    "CallerName",
    "CallerPhone",
    "Handoff",
    "PartOfDay",
    "PartySize",
    "Reason",
    "RelativeDay",
    "Slot",
    "SlotId",
]

CallerEmail = Annotated[
    str,
    Field(
        min_length=3,
        max_length=254,
        description=(
            "The caller's email address, spelled back to them and confirmed. "
            "Calendly needs it to book and sends the booking details there."
        ),
    ),
]
CallerPhone = Annotated[
    str | None,
    Field(
        max_length=50,
        description=(
            "The caller's phone number, digits only, as confirmed back to them. "
            "Leave empty if they did not give one."
        ),
    ),
]

PartySize = Annotated[
    int | None,
    Field(
        ge=1,
        le=500,
        description=(
            "How many people the booking is for (a table for four: 4), if the "
            "caller said. Leave empty for a booking that isn't for a group."
        ),
    ),
]

# Why the agent should pass the caller to a person instead of booking:
# booking_off (the owner switched AI booking off), not_set_up (no Calendly
# event chosen yet), fully_booked (nothing free in the whole horizon),
# plan_required (Calendly asked for a plan upgrade to book), cannot_book
# (Calendly refused, e.g. the event asks questions the agent cannot answer),
# unconfirmed (Calendly did not answer in time: the booking may or may not
# have been made, so it must not be tried again).
Handoff = Literal[
    "booking_off",
    "not_set_up",
    "fully_booked",
    "plan_required",
    "cannot_book",
    "unconfirmed",
]
HANDOFF_FIELD = Field(
    default=None,
    description=(
        "Set when this request needs a person: read 'say', then transfer the "
        "caller if you can, otherwise take their name, number and request so "
        "the team can call back. Never book around it."
    ),
)


class AvailabilityResult(BaseModel):
    slots: list[Slot]
    say: str = Field(description="Read this to the caller word for word.")
    handoff: Handoff | None = HANDOFF_FIELD


class BookingResult(BaseModel):
    booked: bool
    event_id: str | None = Field(
        default=None, description="Id of the new Calendly booking, when booked."
    )
    slots: list[Slot] | None = Field(
        default=None, description="Alternatives, when the time was taken."
    )
    say: str = Field(description="Read this to the caller word for word.")
    handoff: Handoff | None = HANDOFF_FIELD
    starts_at: str | None = Field(
        default=None, description="ISO start time in the business's zone, when booked."
    )
    needs_email: bool | None = Field(
        default=None,
        description="True: Calendly did not accept the email address. Ask for "
        "it again, spell it back, then book again.",
    )


class Booking(BaseModel):
    """One booking the agent made, as read back from Calendly."""

    event_id: str
    start: datetime
    end: datetime
    status: Literal["confirmed", "cancelled"]
    caller_name: str | None = None
    caller_phone: str | None = None
    party_size: int | None = None
    reason: str | None = None
    created_at: datetime | None = None
