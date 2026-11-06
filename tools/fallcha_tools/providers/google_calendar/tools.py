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
    BookingDay,
    BookingName,
    BookingPhone,
    BookingResult,
    CallerName,
    CallerPhone,
    CancelResult,
    EventId,
    FindBookingResult,
    PartOfDay,
    PartySize,
    Reason,
    RelativeDay,
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
        or, when "handoff" is set, transfer or take a message instead."""
        svc = await service()
        return await _guard(
            svc.book(slot_id, caller_name, caller_phone, reason, party_size)
        )

    @mcp.tool(annotations=_READ_ONLY, title="Find a caller's booking")
    async def find_booking(
        caller_phone: BookingPhone,
        caller_name: BookingName = None,
        booking_day: BookingDay = None,
    ) -> FindBookingResult:
        """Use when a caller wants to cancel or move a booking made on an
        earlier call. Ask for the phone number the booking was made under, and
        their name or the day of the booking, then call this. Read the "say"
        field, confirm which booking with the caller, then use its event_id
        with cancel_appointment or move_appointment. If "handoff" is set, do
        not change anything: transfer the caller if you can, otherwise take a
        message for the team."""
        svc = await service()
        return await _guard(svc.find_booking(caller_phone, caller_name, booking_day))

    @mcp.tool(annotations=_WRITES, title="Move a booking to a new time")
    async def move_appointment(event_id: EventId, slot_id: SlotId) -> BookingResult:
        """Move a booking found with find_booking (or made earlier on this
        call) to a new time. First check free times with
        check_appointment_availability, let the caller choose, read the new
        time back and get a yes. The new time is booked before the old one is
        removed. Read the "say" field; if "booked" is false, offer the
        alternatives or follow "handoff"."""
        svc = await service()
        return await _guard(svc.move(event_id, slot_id))

    @mcp.tool(
        annotations={**_WRITES, "destructiveHint": True},
        title="Cancel an appointment it booked",
    )
    async def cancel_appointment(event_id: EventId) -> CancelResult:
        """Cancel a booking, using the event_id that book_appointment returned
        on this call or that find_booking found. Confirm with the caller first.
        Only bookings made through this agent can be cancelled. Read the "say"
        field to the caller."""
        svc = await service()
        return await _guard(svc.cancel(event_id))
