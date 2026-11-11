"""What the caller told the agent, for the Bookings screen.

A calendar keeps only what its booking form has room for: Calendly drops the
phone number unless the event type asks for one, and has nowhere for a party
size. The agent passed both to the booking tool, and LightMove keeps that in
the call's record (``gathered_context``), so the screen fills in what the
calendar left out from the call that made the booking.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from api.schemas.integrations import CalendarBooking

# Tools that leave a booking on the calendar, by the end of their name (MCP
# tools are prefixed with the provider, e.g. "mcp__calendly__book_appointment").
_BOOKING_TOOLS = ("book_appointment", "reschedule_appointment")


@dataclass(frozen=True, slots=True)
class CallerDetails:
    name: str | None = None
    phone: str | None = None
    party_size: int | None = None


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _count(value: Any) -> int | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return None
    number = int(digits)
    return number if 0 < number < 1000 else None


def _result(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    raw = record.get("result")
    if isinstance(raw, Mapping):
        return raw
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
    return parsed if isinstance(parsed, Mapping) else None


def details_by_event(
    calls: Iterable[tuple[int, Mapping[str, Any]]],
) -> dict[str, CallerDetails]:
    """Event id -> what the caller gave, from each call's booking tool
    results (``(run id, gathered_context)`` pairs). The tool's own arguments
    win; what the agent wrote down on the call fills the gaps."""
    found: dict[str, CallerDetails] = {}
    for _run_id, gathered in calls:
        if not isinstance(gathered, Mapping):
            continue
        for record in gathered.get("tool_results") or ():
            if not isinstance(record, Mapping) or record.get("status") != "completed":
                continue
            name = str(record.get("function_name") or "")
            if not name.endswith(_BOOKING_TOOLS):
                continue
            result = _result(record)
            event_id = _text(result.get("event_id")) if result else None
            if not event_id:
                continue
            args = record.get("arguments")
            args = args if isinstance(args, Mapping) else {}
            found[event_id] = CallerDetails(
                name=_text(args.get("caller_name"))
                or _text(gathered.get("caller_name")),
                phone=_text(args.get("caller_phone"))
                or _text(gathered.get("callback_number"))
                or _text(gathered.get("caller_phone")),
                party_size=_count(args.get("party_size"))
                or _count(gathered.get("party_size")),
            )
    return found


def fill_in(
    bookings: Sequence[CalendarBooking], details: Mapping[str, CallerDetails]
) -> list[CalendarBooking]:
    """The bookings, with what the calendar left out taken from the call.
    What the calendar has is never replaced."""
    filled: list[CalendarBooking] = []
    for booking in bookings:
        known = details.get(booking.event_id)
        if known is None:
            filled.append(booking)
            continue
        filled.append(
            booking.model_copy(
                update={
                    "caller_name": booking.caller_name or known.name,
                    "caller_phone": booking.caller_phone or known.phone,
                    "party_size": booking.party_size or known.party_size,
                }
            )
        )
    return filled
