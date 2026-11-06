"""Cancelling or moving a booking made on an earlier call: only when the
owner allows it, and only after the caller's details match the booking.
Google is respx-mocked; no database."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from pydantic import JsonValue

from fallcha_tools.core.models import AuthMode
from fallcha_tools.core.provider import ConnectionContext
from fallcha_tools.providers.google_calendar import GoogleCalendarProvider
from fallcha_tools.providers.google_calendar.credentials import TokenCache
from fallcha_tools.providers.google_calendar.errors import BadArgumentError
from fallcha_tools.providers.google_calendar.service import (
    CalendarService,
    _same_name,
    _same_phone,
)
from tests.google_fakes import (
    BOOKING_KEY,
    FakeClock,
    FakeGoogle,
    calendar_config,
    service_account_key,
)

DUBLIN = ZoneInfo("Europe/Dublin")


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=DUBLIN)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()  # Monday 12 October 2026, 07:00 Dublin


@pytest.fixture
def google() -> Iterator[FakeGoogle]:
    with respx.mock(assert_all_called=False) as router:
        yield FakeGoogle(router)


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def provider(clock: FakeClock) -> GoogleCalendarProvider:
    return GoogleCalendarProvider(
        booking_id_key=BOOKING_KEY, token_cache=TokenCache(clock=clock), clock=clock
    )


def diary(
    provider: GoogleCalendarProvider, http: httpx.AsyncClient, **config: JsonValue
) -> CalendarService:
    ctx = ConnectionContext(
        org_id=1,
        connection_id=uuid.uuid4(),
        provider=provider.id,
        auth_mode=AuthMode.SERVICE_ACCOUNT,
        secret=service_account_key(),
        access_token=None,
        http=http,
        config=calendar_config(**{"ai_changes_enabled": True, **config}),
    )
    return provider.service_for(ctx)


@pytest.mark.parametrize(
    ("given", "stored", "same"),
    [
        ("087 123 4567", "0871234567", True),
        ("+353 87 123 4567", "087 123 4567", True),
        ("0871234568", "0871234567", False),
        ("12345", "12345", False),  # too short to tell
        ("0871234567", None, False),
    ],
)
def test_phone_numbers_compare_by_their_last_nine_digits(
    given: str, stored: str | None, same: bool
) -> None:
    assert _same_phone(given, stored) is same


def test_names_match_on_any_shared_word() -> None:
    assert _same_name("Byrne", "Mary Byrne")
    assert _same_name("mary", "Mary Byrne")
    assert not _same_name("Murphy", "Mary Byrne")
    assert not _same_name("M", "Mary Byrne")


async def test_changes_are_off_unless_the_owner_allows_them(
    provider: GoogleCalendarProvider, http: httpx.AsyncClient, google: FakeGoogle
) -> None:
    svc = diary(provider, http, ai_changes_enabled=False)

    found = await svc.find_booking("0871234567", "Byrne", None)
    moved = await svc.move("anything", at(14, 10).isoformat())

    assert found.handoff == "changes_off" and found.bookings == []
    assert moved.handoff == "changes_off" and moved.booked is False
    assert not google.list_events.called and not google.insert.called


async def test_a_booking_is_found_by_phone_and_name_or_day(
    provider: GoogleCalendarProvider, http: httpx.AsyncClient, google: FakeGoogle
) -> None:
    svc = diary(provider, http)
    made = await svc.book(at(14, 10).isoformat(), "Mary Byrne", "087 123 4567")
    assert made.booked

    by_name = await svc.find_booking("+353 87 123 4567", "byrne", None)
    by_day = await svc.find_booking("0871234567", None, "wednesday")

    assert [b.event_id for b in by_name.bookings] == [made.event_id]
    assert by_name.say == (
        "I have your booking for Wednesday the fourteenth at ten in the morning. "
        "Is that the one?"
    )
    assert [b.event_id for b in by_day.bookings] == [made.event_id]


@pytest.mark.parametrize(
    ("phone", "name", "day"),
    [
        ("0879999999", "Byrne", None),  # right name, wrong number
        ("0871234567", "Murphy", None),  # right number, wrong name
        ("0871234567", None, "thursday"),  # right number, wrong day
    ],
)
async def test_details_that_do_not_match_hand_off(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    google: FakeGoogle,
    phone: str,
    name: str | None,
    day: str | None,
) -> None:
    svc = diary(provider, http)
    await svc.book(at(14, 10).isoformat(), "Mary Byrne", "087 123 4567")

    found = await svc.find_booking(phone, name, day)

    assert found.bookings == []
    assert found.handoff == "booking_not_found"


async def test_a_number_alone_is_not_enough(
    provider: GoogleCalendarProvider, http: httpx.AsyncClient, google: FakeGoogle
) -> None:
    svc = diary(provider, http)
    with pytest.raises(BadArgumentError, match="name the booking is under"):
        await svc.find_booking("0871234567", None, None)


async def test_cancelled_and_other_calendars_bookings_are_not_found(
    provider: GoogleCalendarProvider, http: httpx.AsyncClient, google: FakeGoogle
) -> None:
    svc = diary(provider, http)
    made = await svc.book(at(14, 10).isoformat(), "Mary Byrne", "0871234567")
    assert made.event_id
    await svc.cancel(made.event_id)
    other = diary(provider, http)  # another connection on the same calendar
    await other.book(at(15, 10).isoformat(), "Mary Byrne", "0871234567")

    found = await svc.find_booking("0871234567", "Byrne", None)

    assert found.handoff == "booking_not_found"


async def test_moving_books_the_new_time_before_removing_the_old(
    provider: GoogleCalendarProvider, http: httpx.AsyncClient, google: FakeGoogle
) -> None:
    svc = diary(provider, http)
    made = await svc.book(
        at(14, 10).isoformat(), "Mary Byrne", "0871234567", "Check-up"
    )
    assert made.event_id

    moved = await svc.move(made.event_id, at(15, 11).isoformat())

    assert moved.booked is True and moved.event_id != made.event_id
    assert (
        moved.say == "Done. Your booking is moved to Thursday the fifteenth at eleven "
        "in the morning."
    )
    assert google.events[made.event_id]["status"] == "cancelled"
    new = google.events[moved.event_id or ""]
    assert new["status"] == "confirmed"
    assert "Mary Byrne" in new["summary"] and "Reason: Check-up" in new["description"]
    # The new booking was written before the old one was removed.
    order = [call.request.method for call in google.router.calls]
    assert order.index("POST", order.index("GET")) < order.index("DELETE")


async def test_moving_to_a_taken_time_keeps_the_old_booking(
    provider: GoogleCalendarProvider, http: httpx.AsyncClient, google: FakeGoogle
) -> None:
    svc = diary(provider, http)
    made = await svc.book(at(14, 10).isoformat(), "Mary Byrne", "0871234567")
    await svc.book(at(15, 11).isoformat(), "Sean Kelly", "0861112222")
    assert made.event_id

    moved = await svc.move(made.event_id, at(15, 11).isoformat())

    assert moved.booked is False
    assert google.events[made.event_id]["status"] == "confirmed"


async def test_moving_a_booking_that_is_not_ours_hands_off(
    provider: GoogleCalendarProvider, http: httpx.AsyncClient, google: FakeGoogle
) -> None:
    svc = diary(provider, http)
    moved = await svc.move("missing-event", at(15, 11).isoformat())
    assert moved.handoff == "booking_not_found"
