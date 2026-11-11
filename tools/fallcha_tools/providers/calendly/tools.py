"""MCP tools. Their signatures and docstrings become the agent's functions.

The names match the Google Calendar tools, so an agent's instructions (and
the platform's call records) work with either calendar.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from fallcha_tools.core.provider import ConnectionContext, ConnectionContextFactory
from fallcha_tools.providers.calendly.client import CalendlyError
from fallcha_tools.providers.calendly.schemas import (
    AvailabilityResult,
    BookingResult,
    CallerEmail,
    CallerName,
    CallerPhone,
    PartOfDay,
    PartySize,
    Reason,
    RelativeDay,
    SlotId,
)
from fallcha_tools.providers.calendly.service import CalendlyService

_READ_ONLY: dict[str, Any] = {"readOnlyHint": True, "openWorldHint": True}
_WRITES: dict[str, Any] = {"readOnlyHint": False, "openWorldHint": True}


async def _guard[T](call: Awaitable[T]) -> T:
    try:
        return await call
    except CalendlyError as exc:
        # Only ToolError messages reach the client (mask_error_details).
        raise ToolError(str(exc)) from None
    except TimeoutError:
        raise ToolError("Calendly did not respond in time") from None


def register_calendly_tools(
    mcp: FastMCP[Any],
    ctx_factory: ConnectionContextFactory,
    service_for: Callable[[ConnectionContext], CalendlyService],
) -> None:
    async def service() -> CalendlyService:
        ctx = await ctx_factory()
        try:
            return service_for(ctx)
        except CalendlyError as exc:
            raise ToolError(str(exc)) from None

    @mcp.tool(annotations=_READ_ONLY, title="Check free times in Calendly")
    async def check_appointment_availability(
        relative_day: RelativeDay = None, part_of_day: PartOfDay = None
    ) -> AvailabilityResult:
        """Use when the caller wants an appointment, to find free times. Returns
        real free times from the business's Calendly. Always call this before
        offering any time, and read the "say" field out word for word; never
        invent a time. If "handoff" is set, do not book: transfer the caller if
        you can, otherwise take their details for the team."""
        svc = await service()
        return await _guard(svc.availability(relative_day, part_of_day))

    @mcp.tool(annotations=_WRITES, title="Book in Calendly")
    async def book_appointment(
        slot_id: SlotId,
        caller_name: CallerName,
        caller_email: CallerEmail,
        caller_phone: CallerPhone = None,
        reason: Reason = None,
        party_size: PartySize = None,
    ) -> BookingResult:
        """Use only after check_appointment_availability returned slots and the
        caller picked one. Calendly needs the caller's email address to book:
        ask for it, spell it back letter by letter and get a yes before calling
        this. Also pass their phone number if they gave one, and how many people
        it is for if they said. Books it in the
        business's Calendly, which emails the caller the details. If "booked"
        is false, read the "say" field: it offers other times, asks for the
        email again ("needs_email"), or, when "handoff" is set, transfer the
        caller or take a message instead. Never call it twice for the same
        booking. This agent cannot cancel or move Calendly bookings: callers
        use the links in their Calendly email, or take a message."""
        svc = await service()
        return await _guard(
            svc.book(
                slot_id,
                caller_name,
                caller_email,
                caller_phone,
                reason,
                party_size=party_size,
            )
        )
