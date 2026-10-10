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
    BookingResult,
    CallerName,
    CallerPhone,
    CancelResult,
    EventId,
    PartOfDay,
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
        relative_day: RelativeDay = None, part_of_day: PartOfDay = None
    ) -> AvailabilityResult:
        """Use when the caller wants a call back, an appointment, an install visit
        or a quote, to find free times. Returns real free slots from the company
        calendar. Always call this before offering any time, and read the "say"
        field out word for word; never invent a time."""
        svc = await service()
        return await _guard(svc.availability(relative_day, part_of_day))

    @mcp.tool(annotations=_WRITES, title="Book an appointment")
    async def book_appointment(
        slot_id: SlotId,
        caller_name: CallerName,
        caller_phone: CallerPhone,
        reason: Reason = None,
    ) -> BookingResult:
        """Use only after check_appointment_availability returned slots and the
        caller picked one and gave their name and phone number. Books the
        appointment on the company calendar. If "booked" is false, read the
        "say" field (it lists alternatives) and try again with a new slot id."""
        svc = await service()
        return await _guard(svc.book(slot_id, caller_name, caller_phone, reason))

    @mcp.tool(
        annotations={**_WRITES, "destructiveHint": True},
        title="Cancel an appointment it booked",
    )
    async def cancel_appointment(event_id: EventId) -> CancelResult:
        """Cancel an appointment that book_appointment made earlier, using the
        event_id it returned. Only appointments booked through this agent can be
        cancelled. Read the "say" field to the caller."""
        svc = await service()
        return await _guard(svc.cancel(event_id))
