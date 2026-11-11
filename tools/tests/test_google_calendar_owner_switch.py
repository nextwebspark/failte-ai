"""The owner's switch for changing earlier bookings (``ai_changes_enabled``,
off by default) over find_appointments, reschedule_appointment and
cancel_appointment, and moves that respect the capacity booking rules.
Google is respx-mocked; no database."""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from pydantic import JsonValue

from fallcha_tools.providers.google_calendar import GoogleCalendarProvider
from fallcha_tools.providers.google_calendar.credentials import TokenCache
from fallcha_tools.providers.google_calendar.schemas import RescheduleOutcome
from fallcha_tools.providers.google_calendar.service import (
    PARTY_SIZE_PROP,
    SAY_CHANGES_OFF,
    CalendarService,
)
from tests.google_fakes import BOOKING_KEY, FakeClock, FakeGoogle
from tests.test_google_calendar_service import make_service

DUBLIN = ZoneInfo("Europe/Dublin")
CALLER_ID = "+353871234567"
# Dinner, Thursday to Saturday, with one table released for phone bookings.
ONE_TABLE: dict[str, JsonValue] = {
    "service_periods": [
        {"days": [3, 4, 5], "first_start": "17:00", "last_start": "21:00"}
    ],
    "slot_minutes": 30,
    "booking_minutes": 90,
    "buffer_minutes": 0,
    "max_bookings_at_once": 1,
    "max_guests_at_once": 8,
    "min_lead_hours": 1,
}


def at(day: int, hour: int, minute: int = 0) -> str:
    return datetime(2026, 10, day, hour, minute, tzinfo=DUBLIN).isoformat()


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


@pytest.fixture
def connection_id() -> uuid.UUID:
    return uuid.uuid4()


def calendar(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    **config: JsonValue,
) -> CalendarService:
    svc = make_service(provider, http, connection_id, **config)
    return dataclasses.replace(svc, contact_phone=CALLER_ID)


def made_days_ago(google: FakeGoogle, event_id: str, days: int) -> None:
    created = datetime(2026, 10, 12, 6, 0) - timedelta(days=days)
    google.events[event_id]["created"] = f"{created.isoformat()}.000Z"


def calls(google: FakeGoogle) -> dict[str, int]:
    return {
        "list": google.list_events.call_count,
        "get": google.get_event.call_count,
        "insert": google.insert.call_count,
        "delete": google.delete_event.call_count,
    }


# --- switch off (the default) ------------------------------------------------


async def test_switch_is_off_by_default_and_find_reads_nothing(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    svc = calendar(provider, http, connection_id)

    found = await svc.find(None, "Jane Doe")

    assert found.handoff == "changes_off"
    assert found.appointments == [] and found.say == SAY_CHANGES_OFF
    assert not google.list_events.called


async def test_switch_off_reschedule_touches_nothing(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    svc = calendar(provider, http, connection_id)
    booked = await svc.book(at(12, 10), "Jane Doe", "087 123 4567")
    assert booked.event_id is not None
    before = calls(google)

    result = await svc.reschedule(booked.event_id, at(13, 9))

    assert result.outcome == RescheduleOutcome.HANDED_OFF
    assert result.handoff == "changes_off" and result.event_id is None
    assert calls(google) == before
    assert google.events[booked.event_id]["status"] == "confirmed"


async def test_switch_off_an_earlier_calls_booking_is_not_cancelled(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    svc = calendar(provider, http, connection_id)
    booked = await svc.book(at(12, 10), "Jane Doe", "087 123 4567")
    assert booked.event_id is not None
    made_days_ago(google, booked.event_id, 2)

    result = await svc.cancel(booked.event_id)

    assert result.cancelled is False and result.handoff == "changes_off"
    assert not google.delete_event.called
    assert google.events[booked.event_id]["status"] == "confirmed"


async def test_switch_off_a_booking_without_a_created_time_is_not_cancelled(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    svc = calendar(provider, http, connection_id)
    booked = await svc.book(at(12, 10), "Jane Doe", "087 123 4567")
    assert booked.event_id is not None
    del google.events[booked.event_id]["created"]

    result = await svc.cancel(booked.event_id)

    assert result.handoff == "changes_off" and not google.delete_event.called


async def test_switch_off_this_calls_own_booking_can_still_be_cancelled(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
    clock: FakeClock,
) -> None:
    svc = calendar(provider, http, connection_id)
    booked = await svc.book(at(12, 10), "Jane Doe", "087 123 4567")
    assert booked.event_id is not None
    clock.advance(timedelta(minutes=15))  # later in the same call

    result = await svc.cancel(booked.event_id)

    assert result.cancelled is True and result.handoff is None
    assert google.events[booked.event_id]["status"] == "cancelled"


# --- switch on ---------------------------------------------------------------


async def test_switch_on_an_earlier_calls_booking_is_found_and_cancelled(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    svc = calendar(provider, http, connection_id, ai_changes_enabled=True)
    booked = await svc.book(at(12, 10), "Jane Doe", "087 123 4567")
    assert booked.event_id is not None
    made_days_ago(google, booked.event_id, 2)

    found = await svc.find(None, "Doe")
    assert [a.event_id for a in found.appointments] == [booked.event_id]
    result = await svc.cancel(booked.event_id)

    assert result.cancelled is True


async def test_switch_on_but_booking_off_moves_nothing(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    on = calendar(provider, http, connection_id, ai_changes_enabled=True)
    booked = await on.book(at(12, 10), "Jane Doe", "087 123 4567")
    assert booked.event_id is not None
    paused = calendar(
        provider, http, connection_id, ai_changes_enabled=True, ai_booking_enabled=False
    )

    result = await paused.reschedule(booked.event_id, at(13, 9))

    assert result.outcome == RescheduleOutcome.HANDED_OFF
    assert result.handoff == "booking_off"
    assert "still booked" in result.say
    assert google.insert.call_count == 1
    assert google.events[booked.event_id]["status"] == "confirmed"


# --- moves under capacity rules ------------------------------------------------


def dinner(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    **overrides: JsonValue,
) -> CalendarService:
    return calendar(
        provider,
        http,
        connection_id,
        **{**ONE_TABLE, "ai_changes_enabled": True, **overrides},
    )


def confirmed(google: FakeGoogle) -> list[dict[str, Any]]:
    return [e for e in google.events.values() if e["status"] == "confirmed"]


async def test_a_move_keeps_the_party_size_and_its_one_line(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    svc = dinner(provider, http, connection_id)
    booked = await svc.book(
        at(15, 19), "Mary Byrne", "087 123 4567", "Birthday", party_size=4
    )
    assert booked.event_id is not None

    result = await svc.reschedule(booked.event_id, at(16, 19))

    assert result.outcome == RescheduleOutcome.MOVED, result.say
    [moved] = confirmed(google)
    assert moved["summary"] == "Table for 4 — Mary Byrne"
    assert moved["extendedProperties"]["private"][PARTY_SIZE_PROP] == "4"
    assert moved["description"].count("Party size: 4") == 1
    assert "Reason: Birthday" in moved["description"]


async def test_a_move_into_its_own_time_does_not_count_itself(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    # One table: 19:00-20:30 is ours. Moving to 19:30 overlaps only itself.
    svc = dinner(provider, http, connection_id)
    booked = await svc.book(at(15, 19), "Mary Byrne", "087 123 4567", party_size=2)
    assert booked.event_id is not None

    result = await svc.reschedule(booked.event_id, at(15, 19, 30))

    assert result.outcome == RescheduleOutcome.MOVED, result.say
    [moved] = confirmed(google)
    assert moved["start"]["dateTime"] == at(15, 19, 30)


async def test_a_move_into_a_full_time_keeps_the_old_booking(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    svc = dinner(provider, http, connection_id)
    booked = await svc.book(at(15, 19), "Mary Byrne", "087 123 4567", party_size=2)
    taken = await svc.book(at(16, 19), "Sean Kelly", "086 765 4321", party_size=2)
    assert booked.event_id is not None and taken.booked

    result = await svc.reschedule(booked.event_id, at(16, 19))

    assert result.outcome == RescheduleOutcome.SLOT_TAKEN
    assert google.events[booked.event_id]["status"] == "confirmed"
    assert len(confirmed(google)) == 2


async def test_a_party_now_too_large_is_handed_off(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    svc = dinner(provider, http, connection_id)
    booked = await svc.book(at(15, 19), "Mary Byrne", "087 123 4567", party_size=6)
    assert booked.event_id is not None
    stricter = dinner(provider, http, connection_id, max_party_size=4)

    result = await stricter.reschedule(booked.event_id, at(16, 19))

    assert result.outcome == RescheduleOutcome.HANDED_OFF
    assert result.handoff == "party_too_large"
    assert google.events[booked.event_id]["status"] == "confirmed"
