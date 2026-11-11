"""The Bookings screen fills in what the calendar didn't keep from the call
that made the booking (api/services/tool_integrations/booking_details.py)."""

import json
import uuid
from datetime import UTC, datetime

from api.schemas.integrations import CalendarBooking
from api.services.tool_integrations.booking_details import (
    CallerDetails,
    details_by_event,
    fill_in,
)


def _booked(event_id, **arguments):
    return {
        "function_name": "mcp__calendly__book_appointment",
        "status": "completed",
        "arguments": arguments,
        "result": json.dumps({"booked": True, "event_id": event_id}),
    }


def _booking(event_id, **fields):
    return CalendarBooking(
        event_id=event_id,
        start=datetime(2026, 11, 12, 13, tzinfo=UTC),
        end=datetime(2026, 11, 12, 13, 30, tzinfo=UTC),
        status="confirmed",
        connection_id=uuid.uuid4(),
        **fields,
    )


def test_details_come_from_the_booking_tool_then_the_call():
    calls = [
        (
            1,
            {
                "party_size": "3 people",
                "callback_number": "0851234567",
                "tool_results": [
                    _booked("ev1", caller_name="Niamh", caller_phone="087 555 0100")
                ],
            },
        ),
        (
            2,
            {
                "party_size": "",
                "tool_results": [_booked("ev2", caller_name="Seán", party_size=4)],
            },
        ),
        # A refused booking or another tool leaves nothing behind.
        (
            3,
            {
                "tool_results": [
                    {
                        "function_name": "book_appointment",
                        "status": "completed",
                        "result": '{"booked": false}',
                    },
                    {
                        "function_name": "check_appointment_availability",
                        "status": "completed",
                        "result": "{}",
                    },
                ]
            },
        ),
    ]
    assert details_by_event(calls) == {
        "ev1": CallerDetails(name="Niamh", phone="087 555 0100", party_size=3),
        "ev2": CallerDetails(name="Seán", phone=None, party_size=4),
    }


def test_the_calendar_wins_and_gaps_are_filled():
    details = {"ev1": CallerDetails(name="Niamh", phone="0851234567", party_size=3)}
    kept = _booking("ev1", caller_name="Niamh Byrne", caller_phone="+353 87 555 0100")
    gap = _booking("ev1")
    other = _booking("ev9")
    filled = fill_in([kept, gap, other], details)
    assert (filled[0].caller_name, filled[0].caller_phone, filled[0].party_size) == (
        "Niamh Byrne",
        "+353 87 555 0100",
        3,
    )
    assert (filled[1].caller_phone, filled[1].party_size) == ("0851234567", 3)
    assert filled[2] == other
