"""Inputs and outputs of the calendar functions, shared by MCP and REST.

The field descriptions double as the agent's function-argument docs, so
they are written for an LLM on a phone call.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

RelativeDay = Annotated[
    str | None,
    Field(
        max_length=100,
        description=(
            "What the caller said about timing, in their own words: 'tomorrow', "
            "'next tuesday', 'this week', 'monday', or a date like 2026-10-12. "
            "Leave empty if they had no preference."
        ),
    ),
]
PartOfDay = Annotated[
    str | None,
    Field(
        max_length=50,
        description=(
            "'morning', 'afternoon' or 'evening' if the caller said so, "
            "otherwise empty."
        ),
    ),
]
PartySize = Annotated[
    int | None,
    Field(
        ge=1,
        le=1000,
        description=(
            "How many people the booking is for, as the caller said. Required "
            "when the result asks for it; otherwise leave empty."
        ),
    ),
]
SlotId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        description=(
            "The exact id string of the slot the caller chose, copied from the "
            "check_appointment_availability response. Never make this up and "
            "never reformat it."
        ),
    ),
]
CallerName = Annotated[
    str,
    Field(
        min_length=1, max_length=200, description="The caller's name as they gave it."
    ),
]
CallerPhone = Annotated[
    str,
    Field(
        min_length=1,
        max_length=50,
        description=(
            "The caller's phone number, digits only, as confirmed back to them."
        ),
    ),
]
Reason = Annotated[
    str | None,
    Field(
        max_length=500,
        description="One short line on what the call is about.",
    ),
]
EventId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=1024,
        description="The event_id returned by book_appointment for this booking.",
    ),
]


# Why the agent should pass the caller to a person instead of booking:
# booking_off (the owner switched AI booking off), party_too_large /
# party_too_small (outside the party sizes the agent may book), fully_booked
# (nothing free in the whole booking horizon).
Handoff = Literal["booking_off", "party_too_large", "party_too_small", "fully_booked"]
HANDOFF_FIELD = Field(
    default=None,
    description=(
        "Set when this request needs a person: read 'say', then transfer the "
        "caller if you can, otherwise take their name, number and request so "
        "the team can call back. Never book around it."
    ),
)


class Slot(BaseModel):
    id: str = Field(description="Opaque slot id to pass to book_appointment.")
    say: str = Field(description="How to say this slot out loud.")


class AvailabilityResult(BaseModel):
    slots: list[Slot]
    say: str = Field(description="Read this to the caller word for word.")
    handoff: Handoff | None = HANDOFF_FIELD
    needs_party_size: bool | None = Field(
        default=None,
        description="True: ask how many people, then check again with party_size.",
    )


class BookingResult(BaseModel):
    booked: bool
    event_id: str | None = Field(
        default=None, description="Id of the new event, when booked."
    )
    slots: list[Slot] | None = Field(
        default=None, description="Alternatives, when the slot was taken."
    )
    say: str = Field(description="Read this to the caller word for word.")
    handoff: Handoff | None = HANDOFF_FIELD


class CancelResult(BaseModel):
    cancelled: bool
    say: str = Field(description="Read this to the caller word for word.")


class AvailabilityRequest(BaseModel):
    relative_day: RelativeDay = None
    part_of_day: PartOfDay = None
    party_size: PartySize = None


class BookRequest(BaseModel):
    slot_id: SlotId
    caller_name: CallerName
    caller_phone: CallerPhone
    reason: Reason = None
    party_size: PartySize = None


class CancelRequest(BaseModel):
    event_id: EventId


class Booking(BaseModel):
    """One booking the agent made, as read back from the calendar."""

    event_id: str
    start: datetime
    end: datetime
    status: Literal["confirmed", "cancelled"]
    caller_name: str | None = None
    caller_phone: str | None = None
    party_size: int | None = None
    reason: str | None = None
    created_at: datetime | None = None
