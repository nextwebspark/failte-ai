"""Finding a caller's bookings (find_appointments) against a respx-mocked Google.

The ``service`` fixture is a call from :data:`PHONE`, as the API reports it;
``hidden`` is a call whose number is not known.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

import fallcha_tools.providers.google_calendar.service as calendar_service
from fallcha_tools.providers.google_calendar import GoogleCalendarProvider
from fallcha_tools.providers.google_calendar.credentials import TokenCache
from fallcha_tools.providers.google_calendar.errors import (
    BadArgumentError,
    GoogleApiError,
)
from fallcha_tools.providers.google_calendar.matching import (
    NEED_NAME,
    NEED_PHONE,
    PHONE_KEY_PROPERTY,
    phone_key,
)
from fallcha_tools.providers.google_calendar.schemas import FoundAppointment
from fallcha_tools.providers.google_calendar.service import (
    BOOKING_MARKER,
    CalendarService,
)
from fallcha_tools.providers.google_calendar.speech import NO_BOOKINGS
from tests.google_fakes import BOOKING_KEY, FakeClock, FakeGoogle, google_error
from tests.test_google_calendar_service import make_service

PHONE = "087 123 4567"
NAME = "Jane Doe"
CALLER_ID = "+353871234567"


@pytest.fixture
def provider() -> GoogleCalendarProvider:
    clock = FakeClock()
    return GoogleCalendarProvider(
        booking_id_key=BOOKING_KEY, token_cache=TokenCache(clock=clock), clock=clock
    )


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
def hidden(
    provider: GoogleCalendarProvider, http: httpx.AsyncClient, connection_id: uuid.UUID
) -> CalendarService:
    return make_service(provider, http, connection_id)


@pytest.fixture
def service(hidden: CalendarService) -> CalendarService:
    return dataclasses.replace(hidden, contact_phone=CALLER_ID)


def booking(
    connection_id: uuid.UUID,
    start: str,
    phone: str,
    *,
    event_id: str,
    name: str = "Jane Doe",
    tagged: bool = True,
) -> dict[str, Any]:
    """An event as the service books it. ``tagged=False`` is a booking made
    before bookings carried the phone key (only the description has it)."""
    begin = datetime.fromisoformat(start)
    private = {BOOKING_MARKER: str(connection_id)}
    key = phone_key(phone)
    if tagged and key is not None:
        private[PHONE_KEY_PROPERTY] = key
    return {
        "id": event_id,
        "status": "confirmed",
        "summary": f"Acme call — {name}",
        "description": (
            f"Booked by the LightMove.ai voice agent.\nCaller: {name}\n"
            f"Phone: {phone}\nReason: not given"
        ),
        "start": {"dateTime": begin.isoformat(), "timeZone": "Europe/Dublin"},
        "end": {
            "dateTime": (begin + timedelta(minutes=30)).isoformat(),
            "timeZone": "Europe/Dublin",
        },
        "extendedProperties": {"private": private},
    }


def plant(google: FakeGoogle, *events: dict[str, Any]) -> None:
    for event in events:
        google.events[event["id"]] = event


async def found_ids(
    service: CalendarService, phone: str | None = None, name: str | None = NAME
) -> list[str]:
    return [a.event_id for a in (await service.find(phone, name)).appointments]


# --- matching --------------------------------------------------------------


@pytest.mark.parametrize(
    "spoken",
    [
        "0871234567",
        "087 123 4567",
        "+353 87 123 4567",
        "00353871234567",
        "(087) 123-4567",
        "+353 (0)87 123 4567",
    ],
)
async def test_finds_a_booking_whatever_the_number_format(
    hidden: CalendarService, google: FakeGoogle, spoken: str
) -> None:
    booked = await hidden.book(
        "2026-10-12T10:00:00+01:00", "Jane Doe", "0871234567", None
    )
    assert booked.event_id is not None

    # The number the call comes from, or one the caller says (with the name).
    result = await dataclasses.replace(hidden, contact_phone=spoken).find(None, NAME)
    assert result == await hidden.find(spoken, "jane doe")

    assert result.appointments == [
        FoundAppointment(
            event_id=booked.event_id,
            start="2026-10-12T10:00:00+01:00",
            say="Monday the twelfth at ten in the morning",
        )
    ]
    assert result.say == (
        "I have you booked in for Monday the twelfth at ten in the morning."
    )


async def test_asks_google_for_this_connection_and_number_only(
    service: CalendarService, google: FakeGoogle, connection_id: uuid.UUID
) -> None:
    await service.find(None, NAME)

    queries = [call.request.url.params for call in google.list_events.calls]
    marker = f"{BOOKING_MARKER}={connection_id}"
    assert sorted(tuple(q.get_list("privateExtendedProperty")) for q in queries) == [
        (marker,),  # older bookings, matched on their description
        (marker, f"{PHONE_KEY_PROPERTY}=71234567"),
    ]
    for query in queries:
        # From now until the longest possible horizon (60 days).
        assert query["timeMin"] == "2026-10-12T07:00:00+01:00"
        assert query["timeMax"] == "2026-12-11T07:00:00+00:00"
        assert query["singleEvents"] == "true"
        assert query["orderBy"] == "startTime"
        assert "extendedProperties" in query["fields"]


async def test_older_bookings_are_found_by_their_description(
    service: CalendarService, google: FakeGoogle, connection_id: uuid.UUID
) -> None:
    plant(
        google,
        booking(
            connection_id,
            "2026-10-13T09:00:00+01:00",
            "+353 87 123 4567",
            tagged=False,
            event_id="legacy",
        ),
    )
    result = await service.find(None, NAME)
    assert [a.event_id for a in result.appointments] == ["legacy"]
    assert result.appointments[0].say == "Tuesday the thirteenth at nine in the morning"


async def test_bookings_for_other_numbers_are_never_returned(
    service: CalendarService, google: FakeGoogle, connection_id: uuid.UUID
) -> None:
    plant(
        google,
        booking(connection_id, "2026-10-13T09:00:00+01:00", PHONE, event_id="mine"),
        # Same last seven digits, another network.
        booking(
            connection_id, "2026-10-13T10:00:00+01:00", "086 123 4567", event_id="o1"
        ),
        booking(
            connection_id, "2026-10-13T11:00:00+01:00", "087 123 4568", event_id="o2"
        ),
        booking(
            connection_id,
            "2026-10-13T12:00:00+01:00",
            "086 123 4567",
            tagged=False,
            event_id="o3",
        ),
        booking(
            connection_id,
            "2026-10-13T13:00:00+01:00",
            "4567",
            tagged=False,
            event_id="o4",
        ),
    )
    assert await found_ids(service) == ["mine"]


async def test_other_connections_manual_and_cancelled_events_are_never_returned(
    service: CalendarService, google: FakeGoogle, connection_id: uuid.UUID
) -> None:
    other = uuid.uuid4()
    manual = booking(connection_id, "2026-10-13T11:00:00+01:00", PHONE, event_id="m")
    del manual["extendedProperties"]
    cancelled = booking(connection_id, "2026-10-13T12:00:00+01:00", PHONE, event_id="c")
    cancelled["status"] = "cancelled"
    plant(
        google,
        booking(other, "2026-10-13T09:00:00+01:00", PHONE, event_id="theirs"),
        booking(
            other, "2026-10-13T10:00:00+01:00", PHONE, tagged=False, event_id="theirs2"
        ),
        manual,
        cancelled,
    )
    assert await found_ids(service) == []

    # Even if Google ignored every filter, nothing that is not ours gets out.
    google.list_events.mock(
        side_effect=lambda _: httpx.Response(
            200, json={"items": list(google.events.values())}
        )
    )
    result = await service.find(None, NAME)
    assert result.appointments == []
    assert result.say == NO_BOOKINGS


async def test_the_name_must_match_too(
    service: CalendarService, google: FakeGoogle, connection_id: uuid.UUID
) -> None:
    plant(
        google,
        booking(connection_id, "2026-10-13T09:00:00+01:00", PHONE, event_id="jane"),
        booking(
            connection_id,
            "2026-10-13T10:00:00+01:00",
            PHONE,
            name="John Smith",
            tagged=False,
            event_id="john",
        ),
        booking(
            connection_id, "2026-10-13T11:00:00+01:00", "086 765 4321", event_id="x"
        ),
    )
    assert await found_ids(service, name="doe") == ["jane"]
    assert await found_ids(service, name="Jane Doe") == ["jane"]
    # A first name alone is not enough.
    assert await found_ids(service, name="jane") == []
    assert await found_ids(service, name="smith") == ["john"]
    # A miss says the same whether or not the number has bookings.
    missed = await service.find(None, "Mary")
    assert missed.appointments == []
    assert missed.say == NO_BOOKINGS
    # A name never stands in for the number.
    assert await found_ids(service, "086 999 9999", name="Jane Doe") == []


# --- which number a caller may use ------------------------------------------


async def test_the_callers_own_number_still_needs_the_name(
    service: CalendarService, google: FakeGoogle
) -> None:
    # Caller ID can be spoofed: on its own it reveals nothing.
    await service.book("2026-10-13T10:00:00+01:00", NAME, PHONE, None)
    for name in (None, "", "  ", "J."):
        with pytest.raises(BadArgumentError) as caught:
            await service.find(None, name)
        assert str(caught.value) == NEED_NAME
    assert not google.list_events.called
    assert len(await found_ids(service)) == 1


async def test_another_number_needs_the_booked_name(
    service: CalendarService, hidden: CalendarService, google: FakeGoogle
) -> None:
    other = "086 765 4321"
    await service.book("2026-10-13T09:00:00+01:00", "Jane Doe", other, None)
    await service.book("2026-10-13T10:00:00+01:00", "Jane Doe", PHONE, None)

    # Saying the number the call comes from changes nothing.
    assert len(await found_ids(service, "+353 87 123 4567")) == 1
    for caller in (service, hidden):
        for name in (None, "", "  ", "J."):
            with pytest.raises(BadArgumentError) as caught:
                await caller.find(other, name)
            assert str(caught.value) == NEED_NAME
        assert len(await found_ids(caller, other, "Jane Doe")) == 1
        # Every word given must be in the booked name.
        assert await found_ids(caller, other, "Jane Smith") == []
        assert await found_ids(caller, other, "Mary") == []


@pytest.mark.parametrize("contact", [None, "", "unknown", "anonymous", "+353 87"])
async def test_a_hidden_number_needs_a_spoken_one(
    hidden: CalendarService, google: FakeGoogle, contact: str | None
) -> None:
    caller = dataclasses.replace(hidden, contact_phone=contact)
    for name in (None, "Jane Doe"):
        with pytest.raises(BadArgumentError) as caught:
            await caller.find(None, name)
        assert str(caught.value) == NEED_PHONE
    assert not google.list_events.called


# --- numbers that share the 8-digit key -------------------------------------


async def test_numbers_sharing_the_key_are_told_apart_in_full(
    hidden: CalendarService, google: FakeGoogle, connection_id: uuid.UUID
) -> None:
    dublin, cork = "01 412 3456", "021 412 3456"
    assert phone_key(dublin) == phone_key(cork)
    plant(
        google,
        booking(connection_id, "2026-10-13T09:00:00+01:00", dublin, event_id="d"),
        booking(
            connection_id,
            "2026-10-13T10:00:00+01:00",
            cork,
            tagged=False,
            event_id="c",
        ),
    )
    # Europe/Dublin gives the region (IE) for numbers said without +353.
    assert await found_ids(hidden, "+353 1 412 3456") == ["d"]
    assert await found_ids(hidden, cork) == ["c"]
    from_cork = dataclasses.replace(hidden, contact_phone="+353214123456")
    assert await found_ids(from_cork) == ["c"]


async def test_us_area_codes_with_a_configured_region(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    new_york, chicago = "212 555 1234", "312 555 1234"
    assert phone_key(new_york) == phone_key(chicago)
    # A US business whose calendar runs on UTC: the region must be set.
    service = make_service(
        provider, http, connection_id, timezone="UTC", phone_region="us"
    )
    plant(
        google,
        booking(connection_id, "2026-10-13T09:00:00+01:00", new_york, event_id="ny"),
        booking(connection_id, "2026-10-13T10:00:00+01:00", chicago, event_id="chi"),
    )
    assert await found_ids(service, "+1 212 555 1234") == ["ny"]
    assert await found_ids(service, chicago) == ["chi"]


async def test_numbers_that_do_not_parse_fall_back_to_the_key(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    # No region (UTC is no country), so national numbers cannot be parsed.
    service = make_service(provider, http, connection_id, timezone="UTC")
    plant(
        google,
        booking(connection_id, "2026-10-13T09:00:00+01:00", PHONE, event_id="a"),
    )
    assert await found_ids(service, "+353 87 123 4567") == ["a"]
    assert await found_ids(service, "0871234567") == ["a"]


# --- window and limits -----------------------------------------------------


async def test_only_upcoming_bookings_soonest_first_at_most_three(
    service: CalendarService, google: FakeGoogle, connection_id: uuid.UUID
) -> None:
    plant(
        google,
        booking(connection_id, "2026-10-20T09:00:00+01:00", PHONE, event_id="d"),
        booking(connection_id, "2026-10-13T09:00:00+01:00", PHONE, event_id="b"),
        booking(
            connection_id,
            "2026-10-14T09:00:00+01:00",
            PHONE,
            tagged=False,
            event_id="c",
        ),
        booking(connection_id, "2026-10-12T10:00:00+01:00", PHONE, event_id="a"),
        # Started a quarter of an hour ago, so Google still lists it.
        booking(connection_id, "2026-10-12T06:45:00+01:00", PHONE, event_id="now"),
        booking(connection_id, "2026-10-09T09:00:00+01:00", PHONE, event_id="past"),
    )
    result = await service.find(None, NAME)
    assert [a.event_id for a in result.appointments] == ["a", "b", "c"]
    assert result.say == (
        "I have you booked in for Monday the twelfth at ten in the morning, "
        "Tuesday the thirteenth at nine in the morning, and Wednesday the "
        "fourteenth at nine in the morning."
    )


async def test_nothing_upcoming(
    service: CalendarService, google: FakeGoogle, connection_id: uuid.UUID
) -> None:
    plant(
        google,
        booking(connection_id, "2026-10-09T09:00:00+01:00", PHONE, event_id="past"),
        booking(connection_id, "2026-12-14T09:00:00+00:00", PHONE, event_id="far"),
    )
    result = await service.find(None, NAME)
    assert result.appointments == []
    assert result.say == NO_BOOKINGS


@pytest.mark.parametrize("phone", ["087", "123 456", "call me", "+353 87"])
async def test_too_short_numbers_are_refused_before_calling_google(
    service: CalendarService, google: FakeGoogle, phone: str
) -> None:
    with pytest.raises(BadArgumentError, match="at least 7 digits"):
        await service.find(phone, "Jane Doe")
    assert not google.list_events.called
    assert not google.token.called


async def test_untagged_scan_is_capped_but_tagged_bookings_are_always_found(
    service: CalendarService,
    google: FakeGoogle,
    connection_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(calendar_service, "SCAN_PAGE_SIZE", 2)
    others = [
        booking(
            connection_id,
            f"2026-10-{13 + day}T09:00:00+01:00",
            "086 765 4321",
            tagged=False,
            event_id=f"other{day}",
        )
        for day in range(4)
    ]
    plant(
        google,
        *others,
        booking(
            connection_id,
            "2026-10-19T09:00:00+01:00",
            PHONE,
            tagged=False,
            event_id="legacy",
        ),
        booking(connection_id, "2026-10-20T09:00:00+01:00", PHONE, event_id="tagged"),
    )

    # The scan reads the soonest 2 x 2 bookings, so it misses "legacy"; the
    # tagged booking is found by Google's filter however busy the calendar is.
    assert await found_ids(service) == ["tagged"]
    scans = [
        call.request.url.params
        for call in google.list_events.calls
        if len(call.request.url.params.get_list("privateExtendedProperty")) == 1
    ]
    assert [scan.get("pageToken") for scan in scans] == [None, "2"]


async def test_no_further_page_without_time_left(
    service: CalendarService,
    google: FakeGoogle,
    connection_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(calendar_service, "SCAN_PAGE_SIZE", 1)
    plant(
        google,
        booking(
            connection_id,
            "2026-10-13T09:00:00+01:00",
            PHONE,
            tagged=False,
            event_id="1",
        ),
        booking(
            connection_id,
            "2026-10-14T09:00:00+01:00",
            PHONE,
            tagged=False,
            event_id="2",
        ),
    )

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.2)
        return google._list_events(request)

    google.list_events.mock(side_effect=slow)
    hurried = dataclasses.replace(service, deadline_seconds=0.5, min_page_seconds=0.4)

    assert await found_ids(hurried) == ["1"]  # the soonest, not a timeout
    assert google.list_events.call_count == 2  # tagged + first scan page


async def test_google_failures_become_clear_errors(
    service: CalendarService, google: FakeGoogle
) -> None:
    google.list_events.mock(
        side_effect=None, return_value=google_error(404, "notFound")
    )
    with pytest.raises(GoogleApiError, match="the calendar was not found"):
        await service.find(None, NAME)

    google.list_events.mock(
        return_value=httpx.Response(200, json={"items": {"id": "x"}})
    )
    with pytest.raises(GoogleApiError, match="unreadable event list"):
        await service.find(None, NAME)


# --- with cancel ------------------------------------------------------------


async def test_a_booking_from_an_earlier_call_can_be_cancelled(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    first_call = make_service(provider, http, connection_id)
    booked = await first_call.book(
        "2026-10-12T10:00:00+01:00", "Jane Doe", "0871234567", None
    )

    later_call = dataclasses.replace(
        make_service(provider, http, connection_id), contact_phone=CALLER_ID
    )
    found = await later_call.find(None, NAME)
    assert [a.event_id for a in found.appointments] == [booked.event_id]
    cancelled = await later_call.cancel(found.appointments[0].event_id)
    assert cancelled.cancelled is True
    assert await found_ids(later_call) == []
