"""Moving a booking (reschedule_appointment) against a respx-mocked Google."""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
import respx

from fallcha_tools.providers.google_calendar import GoogleCalendarProvider
from fallcha_tools.providers.google_calendar.credentials import TokenCache
from fallcha_tools.providers.google_calendar.errors import (
    BadArgumentError,
    GoogleApiError,
)
from fallcha_tools.providers.google_calendar.matching import PHONE_KEY_PROPERTY
from fallcha_tools.providers.google_calendar.schemas import (
    RescheduleOutcome,
    RescheduleResult,
)
from fallcha_tools.providers.google_calendar.service import (
    MOVE_NOT_FOUND,
    CalendarService,
)
from tests.google_fakes import BOOKING_KEY, FakeClock, FakeGoogle, google_error
from tests.test_google_calendar_find import (
    CALLER_ID,
    PHONE,
    booking,
    found_ids,
    plant,
)
from tests.test_google_calendar_service import make_service

OLD_SLOT = "2026-10-12T10:00:00+01:00"
NEW_SLOT = "2026-10-13T09:00:00+01:00"


@pytest.fixture
def google() -> Iterator[FakeGoogle]:
    with respx.mock(assert_all_called=False) as router:
        yield FakeGoogle(router)


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def connection_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def service(http: httpx.AsyncClient, connection_id: uuid.UUID) -> CalendarService:
    clock = FakeClock()
    provider = GoogleCalendarProvider(
        booking_id_key=BOOKING_KEY, token_cache=TokenCache(clock=clock), clock=clock
    )
    calling = make_service(provider, http, connection_id)
    return dataclasses.replace(calling, contact_phone=CALLER_ID)


async def book_old(service: CalendarService, reason: str | None = "Check-up") -> str:
    booked = await service.book(OLD_SLOT, "Jane Doe", PHONE, reason)
    assert booked.event_id is not None
    return booked.event_id


def confirmed(google: FakeGoogle) -> dict[str, dict[str, Any]]:
    return {
        event_id: event
        for event_id, event in google.events.items()
        if event["status"] == "confirmed"
    }


async def test_books_the_new_time_for_the_same_caller_then_cancels_the_old(
    service: CalendarService, google: FakeGoogle
) -> None:
    old_id = await book_old(service)

    def delete_after_insert(request: httpx.Request) -> httpx.Response:
        # By the time the old booking goes, the new one is already in.
        assert len(confirmed(google)) == 2
        return google._delete_event(request)

    google.delete_event.mock(side_effect=delete_after_insert)

    result = await service.reschedule(old_id, NEW_SLOT)

    assert result.outcome == RescheduleOutcome.MOVED
    assert result.say == (
        "Your appointment is moved from Monday the twelfth at ten in the morning "
        "to Tuesday the thirteenth at nine in the morning."
    )
    assert result.event_id is not None and result.event_id != old_id
    assert list(confirmed(google)) == [result.event_id]
    new = google.events[result.event_id]
    assert new["start"]["dateTime"] == NEW_SLOT
    assert new["summary"] == "Acme call — Jane Doe"
    assert (
        "Caller: Jane Doe\nPhone: 087 123 4567\nReason: Check-up"
        in (new["description"])
    )
    assert new["extendedProperties"]["private"][PHONE_KEY_PROPERTY] == "71234567"
    assert await found_ids(service) == [result.event_id]


async def test_a_retry_after_a_lost_reply_finds_its_own_booking(
    service: CalendarService, google: FakeGoogle
) -> None:
    old_id = await book_old(service)
    # The first attempt booked the new time but its reply never arrived.
    first = await service.book(NEW_SLOT, "Jane Doe", PHONE, "Check-up")

    result = await service.reschedule(old_id, NEW_SLOT)

    assert result.outcome == RescheduleOutcome.MOVED
    assert result.event_id == first.event_id
    assert list(confirmed(google)) == [first.event_id]


async def test_a_taken_slot_keeps_the_old_booking(
    service: CalendarService, google: FakeGoogle
) -> None:
    old_id = await book_old(service)
    google.busy.append({"start": "2026-10-13T08:00:00Z", "end": "2026-10-13T09:00:00Z"})

    result = await service.reschedule(old_id, NEW_SLOT)

    assert result.outcome == RescheduleOutcome.SLOT_TAKEN
    assert result.event_id is None
    assert result.slots
    assert result.say.startswith("That one has just gone. I have ")
    assert result.say.endswith(
        "Your appointment for Monday the twelfth at ten in the morning is still booked."
    )
    assert list(confirmed(google)) == [old_id]
    assert not google.delete_event.called


async def test_a_failed_cancel_keeps_both_and_says_so(
    service: CalendarService, google: FakeGoogle
) -> None:
    old_id = await book_old(service)
    google.delete_event.mock(side_effect=None, return_value=google_error(503))

    result = await service.reschedule(old_id, NEW_SLOT)

    assert result.outcome == RescheduleOutcome.OLD_NOT_CANCELLED
    assert result.event_id is not None
    assert result.say == (
        "You are booked in for Tuesday the thirteenth at nine in the morning, "
        "but I could not cancel your appointment for Monday the twelfth at ten "
        "in the morning, so the team will need to remove it."
    )
    assert set(confirmed(google)) == {old_id, result.event_id}


async def test_a_failed_booking_leaves_the_old_one_alone(
    service: CalendarService, google: FakeGoogle
) -> None:
    old_id = await book_old(service)
    google.insert.mock(side_effect=None, return_value=google_error(500))

    with pytest.raises(GoogleApiError, match="temporarily unavailable"):
        await service.reschedule(old_id, NEW_SLOT)

    assert list(confirmed(google)) == [old_id]
    assert not google.delete_event.called


@pytest.mark.parametrize("same", [OLD_SLOT, "2026-10-12T09:00:00Z"])
async def test_the_same_time_changes_nothing(
    service: CalendarService, google: FakeGoogle, same: str
) -> None:
    old_id = await book_old(service)
    inserts = google.insert.call_count

    result = await service.reschedule(old_id, same)

    assert result == RescheduleResult(
        outcome=RescheduleOutcome.UNCHANGED,
        say="You are already booked in for Monday the twelfth at ten in the morning.",
    )
    assert google.insert.call_count == inserts
    assert list(confirmed(google)) == [old_id]
    assert not google.delete_event.called


def _not_ours(connection_id: uuid.UUID) -> list[dict[str, Any]]:
    other = booking(uuid.uuid4(), "2026-10-13T11:00:00+01:00", PHONE, event_id="x")
    manual = booking(connection_id, "2026-10-13T12:00:00+01:00", PHONE, event_id="m")
    del manual["extendedProperties"]
    past = booking(connection_id, "2026-10-09T09:00:00+01:00", PHONE, event_id="p")
    cancelled = booking(connection_id, "2026-10-13T13:00:00+01:00", PHONE, event_id="c")
    cancelled["status"] = "cancelled"
    edited = booking(connection_id, "2026-10-13T14:00:00+01:00", PHONE, event_id="e")
    edited["description"] = "Moved to the afternoon by Mary"
    return [other, manual, past, cancelled, edited]


async def test_only_upcoming_bookings_of_this_connection_can_be_moved(
    service: CalendarService, google: FakeGoogle, connection_id: uuid.UUID
) -> None:
    events = _not_ours(connection_id)
    plant(google, *events)

    for event_id in ["missing", *(event["id"] for event in events)]:
        result = await service.reschedule(event_id, NEW_SLOT)
        assert result == RescheduleResult(
            outcome=RescheduleOutcome.NOT_FOUND, say=MOVE_NOT_FOUND
        )
    assert not google.insert.called
    assert not google.delete_event.called


async def test_a_bad_slot_id_is_refused_before_calling_google(
    service: CalendarService, google: FakeGoogle
) -> None:
    with pytest.raises(BadArgumentError, match="ISO timestamp"):
        await service.reschedule("evt", "tomorrow at ten")
    assert not google.token.called
