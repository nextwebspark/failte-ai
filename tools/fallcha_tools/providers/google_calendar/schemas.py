"""Inputs and outputs of the calendar functions, shared by MCP and REST.

The field descriptions double as the agent's function-argument docs, so
they are written for an LLM on a phone call.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

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
        description="'morning' or 'afternoon' if the caller said so, otherwise empty.",
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
        description=(
            "The event_id of the appointment, from book_appointment or "
            "find_appointments. Never make this up."
        ),
    ),
]
BookedPhone = Annotated[
    str | None,
    Field(
        max_length=50,
        description=(
            "Leave empty to look up the number this call comes from. Only if "
            "the caller booked with another number, or the tool asks for it: "
            "that number, including the area code, as confirmed back to them."
        ),
    ),
]
BookedName = Annotated[
    str | None,
    Field(
        max_length=200,
        description=(
            "The full name the appointment was booked under, as the caller "
            "gives it (at least the surname). Always needed."
        ),
    ),
]


class Slot(BaseModel):
    id: str = Field(description="Opaque slot id to pass to book_appointment.")
    say: str = Field(description="How to say this slot out loud.")


class AvailabilityResult(BaseModel):
    slots: list[Slot]
    say: str = Field(description="Read this to the caller word for word.")


class BookingResult(BaseModel):
    booked: bool
    event_id: str | None = Field(
        default=None, description="Id of the new event, when booked."
    )
    slots: list[Slot] | None = Field(
        default=None, description="Alternatives, when the slot was taken."
    )
    say: str = Field(description="Read this to the caller word for word.")


class CancelResult(BaseModel):
    cancelled: bool
    say: str = Field(description="Read this to the caller word for word.")


class FoundAppointment(BaseModel):
    event_id: str = Field(
        description="Pass to cancel_appointment or reschedule_appointment."
    )
    start: str = Field(description="Start time, ISO 8601 in the business's time zone.")
    say: str = Field(description="How to say this appointment out loud.")


class FindResult(BaseModel):
    appointments: list[FoundAppointment] = Field(
        description="The caller's upcoming appointments, soonest first."
    )
    say: str = Field(description="Read this to the caller word for word.")


class RescheduleOutcome(StrEnum):
    MOVED = "moved"
    # The new time is the one already booked: nothing changed.
    UNCHANGED = "unchanged"
    # The new slot was taken: the old booking stands; ``slots`` has others.
    SLOT_TAKEN = "slot_taken"
    # No upcoming booking of this agent has that event_id: nothing changed.
    NOT_FOUND = "not_found"
    # The booking's caller details were edited by staff: nothing changed.
    DETAILS_EDITED = "details_edited"
    # The new time is booked but the old booking could not be cancelled.
    OLD_NOT_CANCELLED = "old_not_cancelled"


class RescheduleResult(BaseModel):
    outcome: RescheduleOutcome
    event_id: str | None = Field(
        default=None, description="Id of the new booking, when one was made."
    )
    starts_at: str | None = Field(
        default=None,
        description=(
            "Start of the new booking, ISO 8601 in the business's time zone, "
            "when one was made."
        ),
    )
    slots: list[Slot] | None = Field(
        default=None, description="Alternatives, when the new slot was taken."
    )
    say: str = Field(description="Read this to the caller word for word.")


class AvailabilityRequest(BaseModel):
    relative_day: RelativeDay = None
    part_of_day: PartOfDay = None


class BookRequest(BaseModel):
    slot_id: SlotId
    caller_name: CallerName
    caller_phone: CallerPhone
    reason: Reason = None


class CancelRequest(BaseModel):
    event_id: EventId
