"""MCP tools. Their signatures and docstrings become the agent's functions."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from fallcha_tools.core.provider import ConnectionContextFactory
from fallcha_tools.providers.google_calendar.errors import CalendarToolError
from fallcha_tools.providers.google_calendar.schemas import (
    AvailabilityResult,
    BookedName,
    BookedPhone,
    BookingResult,
    CallerName,
    CallerPhone,
    CancelResult,
    EventId,
    FindResult,
    PartOfDay,
    PartySize,
    Reason,
    RelativeDay,
    RescheduleResult,
    SlotId,
)
from fallcha_tools.providers.google_calendar.service import (
    CalendarService,
    ServiceFactory,
)

_READ_ONLY: dict[str, Any] = {"readOnlyHint": True, "openWorldHint": True}
_WRITES: dict[str, Any] = {"readOnlyHint": False, "openWorldHint": True}


async def _guard[T](call: Awaitable[T]) -> T:
    try:
        return await call
    except CalendarToolError as exc:
        # Only ToolError messages reach the client (mask_error_details).
        raise ToolError(str(exc)) from None


def register_calendar_tools(
    mcp: FastMCP[Any],
    ctx_factory: ConnectionContextFactory,
    service_for: ServiceFactory,
) -> None:
    async def service() -> CalendarService:
        ctx = await ctx_factory()
        try:
            return service_for(ctx)
        except CalendarToolError as exc:
            raise ToolError(str(exc)) from None

    @mcp.tool(annotations=_READ_ONLY, title="Check free appointment slots")
    async def check_appointment_availability(
        relative_day: RelativeDay = None,
        part_of_day: PartOfDay = None,
        party_size: PartySize = None,
    ) -> AvailabilityResult:
        """Use when the caller wants a booking (a table, an appointment, a visit,
        a call back) to find free times. Returns real free slots from the
        business's calendar. Always call this before offering any time, and read
        the "say" field out word for word; never invent a time. If
        "needs_party_size" is true, ask how many people and call again with
        party_size. If "handoff" is set, do not book: transfer the caller if you
        can, otherwise take their details for the team."""
        svc = await service()
        return await _guard(svc.availability(relative_day, part_of_day, party_size))

    @mcp.tool(annotations=_WRITES, title="Book an appointment")
    async def book_appointment(
        slot_id: SlotId,
        caller_name: CallerName,
        caller_phone: CallerPhone,
        reason: Reason = None,
        party_size: PartySize = None,
    ) -> BookingResult:
        """Use only after check_appointment_availability returned slots and the
        caller picked one and gave their name and phone number (and party size,
        if you checked with one). Books it on the business's calendar. If
        "booked" is false, read the "say" field: it lists alternatives to offer,
        or, when "handoff" is set, transfer or take a message instead. To move
        an existing appointment, use reschedule_appointment instead."""
        svc = await service()
        return await _guard(
            svc.book(slot_id, caller_name, caller_phone, reason, party_size)
        )

    @mcp.tool(
        annotations={**_WRITES, "destructiveHint": True},
        title="Cancel an appointment it booked",
    )
    async def cancel_appointment(event_id: EventId) -> CancelResult:
        """Cancel an appointment booked through this agent, using its event_id:
        from book_appointment in this call, or from find_appointments for a
        booking made on an earlier call. Confirm with the caller which
        appointment it is first. Read the "say" field to the caller; if
        "handoff" is set, nothing was cancelled: transfer the caller or take a
        message."""
        svc = await service()
        return await _guard(svc.cancel(event_id))

    @mcp.tool(annotations=_READ_ONLY, title="Find a caller's appointments")
    async def find_appointments(
        caller_phone: BookedPhone = None, caller_name: BookedName = None
    ) -> FindResult:
        """Use when the caller wants to cancel, move or check an appointment they
        booked on an earlier call. Always ask for the full name the appointment
        was booked under first (at least the surname) and pass it as
        caller_name. Leave caller_phone empty to use the number this call comes
        from; if that finds nothing and they booked with another number, ask
        for that number (confirm it back) and call again with it. Returns their
        upcoming appointments booked through this agent (at most three, soonest
        first), each with its event_id. Read the "say" field to the caller and
        confirm which appointment they mean; never guess one. If none is found,
        offer to take a message. If "handoff" is set, do not change anything:
        transfer the caller if you can, otherwise take a message."""
        svc = await service()
        return await _guard(svc.find(caller_phone, caller_name))

    @mcp.tool(
        annotations={**_WRITES, "destructiveHint": True},
        title="Move an appointment it booked",
    )
    async def reschedule_appointment(
        event_id: EventId, slot_id: SlotId
    ) -> RescheduleResult:
        """Move an appointment to a new time, once the caller confirmed which
        appointment (event_id from find_appointments or book_appointment) and
        picked a new slot from check_appointment_availability. Books the new
        time first and only then cancels the old one, so never cancel it
        yourself. Read the "say" field to the caller. If "outcome" is
        "slot_taken", offer the alternatives in "slots"; if it is
        "old_not_cancelled", the new time is booked: take a message so the team
        removes the old one; if it is "details_edited", take a message so the
        team moves it; if it is "handed_off", nothing changed: follow
        "handoff". On an error, try the same call once more."""
        svc = await service()
        return await _guard(svc.reschedule(event_id, slot_id))
