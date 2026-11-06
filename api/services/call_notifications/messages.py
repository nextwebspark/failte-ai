"""The words of the after-call email and the caller's confirmation text."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from api.services.call_notifications.outcome import (
    CallEvent,
    CallOutcome,
    ConfirmedBooking,
    MissedReason,
    message_details,
)
from api.services.email.base import EmailMessage
from api.services.email.templates import call_notice_message
from api.utils.text import strip_control_characters

_MAX_FIELD = 300

MISSED_REASONS: Mapping[MissedReason, str] = {
    MissedReason.NEVER_CONNECTED: "The call didn't reach the agent.",
    MissedReason.FAULT: "The call dropped because of a technical problem.",
    MissedReason.SILENT: "The caller didn't say anything before the call ended.",
    MissedReason.SHORT_HANGUP: "The caller hung up within a few seconds.",
    MissedReason.TRANSFER_UNANSWERED: (
        "The agent tried to put the caller through to a person, nobody "
        "answered, and no message was taken."
    ),
}

OLD_BOOKING_KEPT_NOTE = (
    "A booking was moved, but the calendar could not remove the old one: "
    "delete it from the calendar so the time is free again."
)

UNCONFIRMED_BOOKING_NOTE = (
    "The agent noted a booking, but the calendar did not confirm one. Check "
    "the calendar and call them back if needed."
)


def _clean(value: str | None) -> str:
    """User or LLM text, on one line and bounded, for subjects and texts."""
    return strip_control_characters(value or "")[:_MAX_FIELD]


def spoken_time(moment: datetime) -> str:
    """7pm, 7:30pm, 12:15am."""
    hour = moment.hour % 12 or 12
    suffix = "am" if moment.hour < 12 else "pm"
    minutes = f":{moment.minute:02d}" if moment.minute else ""
    return f"{hour}{minutes}{suffix}"


def spoken_day(moment: datetime) -> str:
    """Friday 14 Nov. English names regardless of the server's locale."""
    days = (
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    )
    months = (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    )
    return f"{days[moment.weekday()]} {moment.day} {months[moment.month - 1]}"


def spoken_when(moment: datetime) -> str:
    """Friday 14 Nov at 7:30pm, in the calendar's own time (the slot's
    offset), which is the time the caller agreed to."""
    return f"{spoken_day(moment)} at {spoken_time(moment)}"


@dataclass(frozen=True, slots=True)
class CallFacts:
    """What the messages need to know about the call besides its outcome."""

    business_name: str
    # The number the caller dialled (the business's line), as stored.
    business_number: str | None
    # The other party's line: the caller on an inbound call, the person
    # called on an outbound one.
    caller_number: str | None
    called_at: datetime
    call_url: str
    gathered_context: Mapping[str, object]
    inbound: bool = True


def _booking_rows(booking: ConfirmedBooking) -> list[tuple[str, str]]:
    label = "Moved to" if booking.moved else "When"
    rows = [(label, spoken_when(booking.start))]
    if booking.party_size is not None:
        rows.append(("Party size", str(booking.party_size)))
    if booking.caller_name:
        rows.append(("Name", _clean(booking.caller_name)))
    if booking.caller_phone:
        rows.append(("Phone", _clean(booking.caller_phone)))
    return rows


def business_email(
    *, to: str, outcome: CallOutcome, facts: CallFacts
) -> EmailMessage | None:
    """The one email the business gets about this call, or None when the
    call needs no email."""
    business = _clean(facts.business_name)
    called = spoken_when(facts.called_at)
    caller_number = _clean(facts.caller_number) or "a withheld number"
    contact_label = "Called from" if facts.inbound else "Number called"
    details: list[tuple[str, str]]
    note: str | None = None

    if outcome.event is CallEvent.BOOKING_MADE:
        new = [b for b in outcome.bookings if not b.moved]
        moved = [b for b in outcome.bookings if b.moved]
        # Moves and cancellations carry no name: use the one the agent noted.
        noted = _clean(message_details(facts.gathered_context).get("caller_name"))
        if new:
            latest = new[-1]
            who = _clean(latest.caller_name) or noted or caller_number
            subject = f"New booking: {who}, {spoken_when(latest.start)}"
            heading = "New booking"
            summary = f"The agent booked {who} in at {business} on a call on {called}."
        elif moved:
            latest = moved[-1]
            who = noted or caller_number
            subject = f"Booking moved: {who}, {spoken_when(latest.start)}"
            heading = "Booking moved"
            summary = (
                f"The agent moved a booking for {who} at {business} on a call "
                f"on {called}."
            )
        else:
            who = noted or caller_number
            first = outcome.cancelled[0].start
            subject = f"Booking cancelled: {who}" + (
                f", {spoken_when(first)}" if first else ""
            )
            heading = "Booking cancelled"
            summary = (
                f"The agent cancelled a booking for {who} at {business} on a "
                f"call on {called}."
            )
        details = [row for b in outcome.bookings for row in _booking_rows(b)]
        details.extend(
            ("Cancelled", spoken_when(c.start) if c.start else "a booking")
            for c in outcome.cancelled
        )
        details.append((contact_label, caller_number))
        if outcome.old_booking_kept:
            note = OLD_BOOKING_KEPT_NOTE
    elif outcome.event is CallEvent.MESSAGE_TAKEN:
        fields = message_details(facts.gathered_context)
        who = _clean(fields.get("caller_name")) or caller_number
        subject = f"Message from {who}"
        heading = "New message"
        summary = f"The agent took a message for {business} on a call on {called}."
        details = [
            (label, _clean(fields[key]))
            for key, label in (
                ("caller_name", "Name"),
                ("callback_number", "Call back on"),
                ("call_reason", "About"),
            )
            if key in fields
        ]
        details.append((contact_label, caller_number))
        if outcome.unconfirmed_booking_claim:
            note = UNCONFIRMED_BOOKING_NOTE
    elif outcome.event is CallEvent.MISSED_CALL:
        assert outcome.missed_reason is not None
        subject = f"Missed call from {caller_number}"
        heading = "Missed call"
        summary = (
            f"{business} had a call on {called} that the agent couldn't help with."
        )
        details = [
            ("Called from", caller_number),
            ("What happened", MISSED_REASONS[outcome.missed_reason]),
        ]
    else:
        return None

    return call_notice_message(
        to=to,
        subject=subject,
        heading=heading,
        summary=summary,
        details=details,
        note=note,
        call_url=facts.call_url,
    )


def booking_confirmation_text(
    *, booking: ConfirmedBooking, business_name: str, business_number: str | None
) -> str:
    """{Business}: your booking for Friday 14 Nov at 7:30pm, table for 4, is
    confirmed. To change it call +35315550100. A moved booking: "your booking
    is moved to Friday 14 Nov at 7:30pm." """
    when = spoken_when(booking.start)
    party = (
        f", table for {booking.party_size}" if booking.party_size is not None else ""
    )
    if booking.moved:
        text = f"{_clean(business_name)}: your booking is moved to {when}{party}."
    else:
        text = f"{_clean(business_name)}: your booking for {when}{party}, is confirmed."
    number = _clean(business_number)
    text += f" To change it call {number}." if number else " To change it, call us."
    return text
