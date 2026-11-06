"""Booking rules for calendars that hold several bookings at once (restaurant
tables, chairs, rooms): service periods, capacity, party sizes, hand-offs and
the race for the last place. Google is respx-mocked; no database."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx
from pydantic import JsonValue, ValidationError

from fallcha_tools.core.models import AuthMode
from fallcha_tools.core.provider import BookingListProvider, ConnectionContext
from fallcha_tools.providers.google_calendar import GoogleCalendarProvider
from fallcha_tools.providers.google_calendar.credentials import TokenCache
from fallcha_tools.providers.google_calendar.errors import BadArgumentError
from fallcha_tools.providers.google_calendar.scheduling import (
    Booked,
    candidate_slots,
    has_room,
)
from fallcha_tools.providers.google_calendar.service import (
    BOOKING_MARKER,
    PARTY_SIZE_PROP,
    CalendarService,
)
from fallcha_tools.providers.google_calendar.settings import CalendarConfig
from fallcha_tools.providers.google_calendar.speech import say_time
from tests.google_fakes import (
    BOOKING_KEY,
    FakeClock,
    FakeGoogle,
    calendar_config,
    json_body,
    service_account_key,
)

DUBLIN = ZoneInfo("Europe/Dublin")
DINNER: dict[str, JsonValue] = {
    # Thursday to Saturday, first table 17:00, last table 21:00.
    "service_periods": [
        {"days": [3, 4, 5], "first_start": "17:00", "last_start": "21:00"}
    ],
    "slot_minutes": 30,
    "booking_minutes": 90,
    "buffer_minutes": 0,
    "max_bookings_at_once": 2,
    "max_guests_at_once": 10,
    "max_party_size": 8,
    "min_lead_hours": 1,
}


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=DUBLIN)


def config(**overrides: JsonValue) -> CalendarConfig:
    return CalendarConfig.model_validate(calendar_config(**{**DINNER, **overrides}))


def timed_event(
    start: datetime, minutes: int, summary: str, **extra: Any
) -> dict[str, Any]:
    return {
        "id": f"other{uuid.uuid4().hex[:8]}",
        "status": "confirmed",
        "summary": summary,
        "created": "2026-09-01T00:00:00.000Z",
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": (start + timedelta(minutes=minutes)).isoformat()},
        **extra,
    }


# --- settings and pure rules -----------------------------------------------


def test_plain_diary_defaults_do_not_count_capacity() -> None:
    plain = CalendarConfig.model_validate(calendar_config())
    assert not plain.counts_capacity
    assert not plain.needs_party_size
    assert plain.booking_length == plain.slot_minutes
    assert config().counts_capacity
    assert config().needs_party_size


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"max_party_size": 12}, "max_party_size must not be above max_guests_at_once"),
        ({"min_party_size": 4, "max_party_size": 2}, "below min_party_size"),
        (
            {
                "service_periods": [
                    {"days": [3], "first_start": "21:00", "last_start": "17:00"}
                ]
            },
            "first_start must not be after last_start",
        ),
        (
            {
                "service_periods": [
                    {"days": [3], "first_start": "5pm", "last_start": "21:00"}
                ]
            },
            "is not a time like 17:30",
        ),
        ({"max_bookings_at_once": 501}, "less than or equal to 500"),
    ],
)
def test_rules_reject_unsafe_settings(
    overrides: dict[str, JsonValue], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        config(**overrides)


def test_service_periods_give_lunch_and_dinner_starts() -> None:
    cfg = config(
        service_periods=[
            {"days": [3], "first_start": "12:00", "last_start": "13:00"},
            {"days": [3], "first_start": "17:30", "last_start": "18:30"},
        ]
    )
    starts = list(candidate_slots(at(15, 0), at(16, 0), None, cfg))
    assert starts == [
        at(15, 12),
        at(15, 12, 30),
        at(15, 13),
        at(15, 17, 30),
        at(15, 18),
        at(15, 18, 30),
    ]
    assert list(candidate_slots(at(15, 0), at(16, 0), "evening", cfg)) == starts[3:]
    assert list(candidate_slots(at(14, 0), at(15, 0), None, cfg)) == []  # Wednesday


def test_has_room_counts_the_busiest_moment_of_the_stay() -> None:
    cfg = config(max_guests_at_once=None)
    early = Booked(at(15, 17), at(15, 18, 30), guests=2)
    late = Booked(at(15, 18, 30), at(15, 20), guests=2)
    # 17:30-19:00 meets early, then late, never both: one table is enough.
    assert has_room(at(15, 17, 30), [early, late], [], cfg, 2)
    both = Booked(at(15, 17), at(15, 18, 30), guests=2)
    assert not has_room(at(15, 17, 30), [early, both], [], cfg, 2)
    # The table freed at 18:30 can be sold again at 18:30.
    assert has_room(at(15, 18, 30), [early, both], [], cfg, 2)


def test_has_room_respects_guest_limits_and_kitchen_pacing() -> None:
    six = Booked(at(15, 19), at(15, 20, 30), guests=6)
    assert has_room(at(15, 19), [six], [], config(), 4)
    assert not has_room(at(15, 19), [six], [], config(), 5)  # 11 seated > 10
    paced = config(
        max_guests_per_start=8, max_bookings_at_once=5, max_guests_at_once=None
    )
    assert not has_room(at(15, 19), [six], [], paced, 3)  # 9 arriving at 19:00
    assert has_room(at(15, 19, 30), [six], [], paced, 3)


def test_a_blocking_event_closes_the_time() -> None:
    private_party = (at(15, 19), at(15, 23))
    assert not has_room(at(15, 18), [], [private_party], config(), 2)
    assert has_room(at(15, 17), [], [private_party], config(booking_minutes=90), 2)


def test_evening_times_are_said_as_evening() -> None:
    assert (
        say_time(at(15, 19, 30))
        == "Thursday the fifteenth at seven thirty in the evening"
    )
    assert say_time(at(15, 14)) == "Thursday the fifteenth at two in the afternoon"


# --- the service against a mocked Google -------------------------------------


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


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


def context(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    **overrides: JsonValue,
) -> ConnectionContext:
    return ConnectionContext(
        org_id=1,
        connection_id=connection_id,
        provider=provider.id,
        auth_mode=AuthMode.SERVICE_ACCOUNT,
        secret=service_account_key(),
        access_token=None,
        http=http,
        config=calendar_config(**{**DINNER, **overrides}),
    )


def restaurant(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    **overrides: JsonValue,
) -> CalendarService:
    return provider.service_for(context(provider, http, connection_id, **overrides))


async def test_availability_skips_times_with_no_table_left(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    svc = restaurant(provider, http, connection_id)
    # Two phone tables are taken from 17:00 to 18:30 (added by staff).
    google.other_events += [
        timed_event(at(15, 17), 90, "Table for 2 - Byrne"),
        timed_event(at(15, 17), 90, "Murphy 4 pax"),
    ]

    result = await svc.availability("thursday", "evening", party_size=2)

    assert [s.id for s in result.slots] == [
        at(15, 18, 30).isoformat(),
        at(15, 19).isoformat(),
        at(15, 19, 30).isoformat(),
    ]
    assert result.handoff is None
    assert not google.free_busy.called  # capacity reads events, not free/busy


async def test_a_staff_event_without_a_party_size_closes_the_time(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    svc = restaurant(provider, http, connection_id)
    google.other_events += [
        timed_event(at(15, 17), 300, "Private party"),
        timed_event(at(15, 17), 300, "Free event", transparency="transparent"),
    ]
    result = await svc.availability("thursday", None, party_size=2)
    assert all(not s.id.startswith("2026-10-15") for s in result.slots)
    assert result.say.startswith("Nothing free then, but")


async def test_an_all_day_closed_event_closes_the_day_even_when_free(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    svc = restaurant(provider, http, connection_id)
    google.other_events.append(
        {
            "id": "closedday",
            "status": "confirmed",
            "summary": "Closed for staff training",
            "transparency": "transparent",
            "start": {"date": "2026-10-15"},
            "end": {"date": "2026-10-16"},
        }
    )
    result = await svc.availability("thursday", None, party_size=2)
    assert result.slots
    assert all(s.id.startswith("2026-10-16") for s in result.slots)


async def test_booking_writes_the_party_size(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    svc = restaurant(provider, http, connection_id)

    result = await svc.book(
        at(15, 19).isoformat(), "Mary Byrne", "087 123 4567", "Birthday", party_size=4
    )

    assert result.booked is True
    event = json_body(google.insert.calls.last.request)
    assert event["summary"] == "Table for 4 — Mary Byrne"
    assert "Party size: 4" in event["description"]
    assert event["extendedProperties"]["private"] == {
        BOOKING_MARKER: str(connection_id),
        PARTY_SIZE_PROP: "4",
    }
    end = datetime.fromisoformat(event["end"]["dateTime"])
    assert end - datetime.fromisoformat(event["start"]["dateTime"]) == timedelta(
        minutes=90
    )
    assert (
        result.say
        == "That is booked in for Thursday the fifteenth at seven in the evening."
    )


async def test_booking_refuses_a_time_outside_the_service(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    svc = restaurant(provider, http, connection_id)
    result = await svc.book(at(15, 15).isoformat(), "Mary", "0871234567", party_size=2)
    assert result.booked is False
    assert result.slots
    assert not google.insert.called


@pytest.mark.parametrize(
    ("overrides", "party", "handoff"),
    [
        ({"ai_booking_enabled": False}, 2, "booking_off"),
        ({}, 9, "party_too_large"),
        ({"min_party_size": 2}, 1, "party_too_small"),
    ],
)
async def test_requests_that_need_a_person_never_touch_the_calendar(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
    overrides: dict[str, JsonValue],
    party: int,
    handoff: str,
) -> None:
    svc = restaurant(provider, http, connection_id, **overrides)

    checked = await svc.availability("thursday", None, party_size=party)
    booked = await svc.book(
        at(15, 19).isoformat(), "Mary", "0871234567", party_size=party
    )

    assert checked.handoff == handoff and checked.slots == []
    assert booked.handoff == handoff and booked.booked is False
    assert not google.list_events.called and not google.insert.called


async def test_a_switched_off_diary_also_hands_off(
    provider: GoogleCalendarProvider, http: httpx.AsyncClient, google: FakeGoogle
) -> None:
    ctx = ConnectionContext(
        org_id=1,
        connection_id=uuid.uuid4(),
        provider=provider.id,
        auth_mode=AuthMode.SERVICE_ACCOUNT,
        secret=service_account_key(),
        access_token=None,
        http=http,
        config=calendar_config(ai_booking_enabled=False),
    )
    result = await provider.service_for(ctx).availability(None, None)
    assert result.handoff == "booking_off"
    assert not google.free_busy.called


async def test_party_size_is_asked_for_when_the_rules_need_it(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    svc = restaurant(provider, http, connection_id)

    result = await svc.availability("thursday", None)

    assert result.needs_party_size is True
    assert result.say == "How many people is the booking for?"
    with pytest.raises(BadArgumentError, match="party_size is required"):
        await svc.book(at(15, 19).isoformat(), "Mary", "0871234567")


async def test_fully_booked_hands_off(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    svc = restaurant(provider, http, connection_id, max_bookings_at_once=2)
    google.other_events.append(
        {
            "id": "closedall",
            "status": "confirmed",
            "summary": "Closed for renovation",
            "start": {"date": "2026-10-12"},
            "end": {"date": "2026-11-12"},
        }
    )
    result = await svc.availability(None, None, party_size=2)
    assert result.handoff == "fully_booked"
    assert "fully booked for the next 14 days" in result.say


async def test_the_later_of_two_racing_bookings_gives_the_table_back(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    # One table left at 19:00; another replica books it between our check and
    # our insert, so its event is created first.
    svc = restaurant(provider, http, connection_id, max_bookings_at_once=1)
    google.other_events.append(timed_event(at(15, 17), 90, "Table for 2 - Early"))
    real_insert = google.insert.side_effect

    def racing_insert(request: httpx.Request) -> httpx.Response:
        rival = timed_event(at(15, 19), 90, "Table for 2 - Rival")
        rival["created"] = google.created_stamp()
        google.other_events.append(rival)
        assert callable(real_insert)
        response = real_insert(request)
        assert isinstance(response, httpx.Response)
        return response

    google.insert.side_effect = racing_insert

    result = await svc.book(at(15, 19).isoformat(), "Mary", "0871234567", party_size=2)

    assert result.booked is False
    assert google.delete_event.called
    [ours] = google.events.values()
    assert ours["status"] == "cancelled"
    assert all(s.id != at(15, 19).isoformat() for s in result.slots or [])


async def test_the_earlier_booking_keeps_its_table(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    svc = restaurant(provider, http, connection_id, max_bookings_at_once=1)
    real_insert = google.insert.side_effect

    def slower_rival(request: httpx.Request) -> httpx.Response:
        assert callable(real_insert)
        response = real_insert(request)
        assert isinstance(response, httpx.Response)
        rival = timed_event(at(15, 19), 90, "Table for 2 - Rival")
        rival["created"] = google.created_stamp()  # after ours
        google.other_events.append(rival)
        return response

    google.insert.side_effect = slower_rival

    result = await svc.book(at(15, 19).isoformat(), "Mary", "0871234567", party_size=2)

    assert result.booked is True
    assert not google.delete_event.called


async def test_list_bookings_reads_back_this_connections_bookings(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    assert isinstance(provider, BookingListProvider)
    svc = restaurant(provider, http, connection_id)
    booked = await svc.book(
        at(15, 19).isoformat(), "Mary Byrne", "0871234567", "Birthday", party_size=4
    )
    second = await svc.book(at(16, 18).isoformat(), "Sean", "0861112222", party_size=2)
    assert booked.event_id and second.event_id
    await svc.cancel(second.event_id)
    google.other_events.append(timed_event(at(15, 20), 60, "Table for 6 - Walk-in"))

    found = await provider.list_bookings(
        context(provider, http, connection_id), at(12, 0), at(26, 0)
    )

    assert [(b.caller_name, b.party_size, b.status) for b in found] == [
        ("Mary Byrne", 4, "confirmed"),
        ("Sean", 2, "cancelled"),
    ]
    assert found[0].caller_phone == "0871234567"
    assert found[0].reason == "Birthday"
    assert found[1].reason is None
    request = google.list_events.calls.last.request
    assert request.url.params["privateExtendedProperty"] == (
        f"{BOOKING_MARKER}={connection_id}"
    )
    assert request.url.params["showDeleted"] == "true"


async def test_list_bookings_refuses_long_or_reversed_ranges(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
) -> None:
    svc = restaurant(provider, http, connection_id)
    with pytest.raises(BadArgumentError):
        await svc.list_bookings(at(20, 0), at(12, 0))
    with pytest.raises(BadArgumentError):
        await svc.list_bookings(at(1, 0), at(1, 0) + timedelta(days=63))
