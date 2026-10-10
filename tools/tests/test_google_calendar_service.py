"""Calendar service, client and credentials against a respx-mocked Google."""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from pydantic import JsonValue

from fallcha_tools.core.models import AuthMode
from fallcha_tools.core.provider import ConnectionContext
from fallcha_tools.providers.google_calendar import GoogleCalendarProvider
from fallcha_tools.providers.google_calendar.client import (
    CALENDAR_SCOPE,
    SHEETS_READONLY_SCOPE,
)
from fallcha_tools.providers.google_calendar.credentials import (
    GOOGLE_TOKEN_URL,
    CachedToken,
    TokenCache,
)
from fallcha_tools.providers.google_calendar.errors import (
    BadArgumentError,
    GoogleApiError,
    NotConfiguredError,
)
from fallcha_tools.providers.google_calendar.orders import OrdersCache
from fallcha_tools.providers.google_calendar.service import (
    BOOKING_MARKER,
    CalendarService,
    booking_event_id,
)
from fallcha_tools.providers.google_calendar.settings import ServiceAccountKey
from tests.google_fakes import (
    BOOKING_KEY,
    CALENDAR_ID,
    PRIVATE_KEY_PEM,
    PUBLIC_KEY,
    SA_EMAIL,
    SHEET_ID,
    FakeClock,
    FakeGoogle,
    calendar_config,
    form_body,
    google_error,
    json_body,
    service_account_key,
)

ORDERS: list[list[str]] = [
    ["order_id", "customer_name", "address", "eircode", "package", "status", "eta"],
    [
        "VT-1",
        "Jane Murphy",
        "12 Main Street, Galway",
        "H91 X2Y3",
        "Home Fibre",
        "Shipped",
        "Arrives Thursday",
    ],
    [
        "VT-2",
        "John Byrne",
        "Rose Cottage, Kinsale",
        "P17 AB12",
        "Mobile",
        "Pending",
        "",
    ],
]


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def provider(clock: FakeClock) -> GoogleCalendarProvider:
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


def make_service(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    **config: JsonValue,
) -> CalendarService:
    ctx = ConnectionContext(
        org_id=1,
        connection_id=connection_id,
        provider=provider.id,
        auth_mode=AuthMode.SERVICE_ACCOUNT,
        secret=service_account_key(),
        access_token=None,
        http=http,
        config=calendar_config(**config),
    )
    return provider.service_for(ctx)


@pytest.fixture
def service(
    provider: GoogleCalendarProvider, http: httpx.AsyncClient, connection_id: uuid.UUID
) -> CalendarService:
    return make_service(provider, http, connection_id, orders_sheet_id=SHEET_ID)


def _jwt_part(segment: str) -> Any:
    return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))


# --- availability ---------------------------------------------------------


async def test_availability_returns_first_free_slots_in_local_time(
    service: CalendarService, google: FakeGoogle
) -> None:
    result = await service.availability(None, None)

    assert [s.id for s in result.slots] == [
        "2026-10-12T09:00:00+01:00",
        "2026-10-12T09:30:00+01:00",
        "2026-10-12T10:00:00+01:00",
    ]
    assert result.say == (
        "I have Monday the twelfth at nine in the morning, Monday the twelfth at "
        "nine thirty in the morning, or Monday the twelfth at ten in the morning."
    )
    request = google.free_busy.calls.last.request
    assert request.headers["Authorization"] == "Bearer ya29.fake-token"
    body = json_body(request)
    assert body["timeZone"] == "Europe/Dublin"
    assert body["items"] == [{"id": CALENDAR_ID}]
    # Earliest is now + 2h lead; horizon is 14 days.
    assert body["timeMin"] == "2026-10-12T09:00:00+01:00"
    assert body["timeMax"] == "2026-10-26T07:00:00+00:00"


async def test_availability_respects_busy_blocks_buffer_and_part_of_day(
    service: CalendarService, google: FakeGoogle
) -> None:
    # Tuesday 12:00-13:00 local is busy (Google answers in UTC).
    google.busy = [{"start": "2026-10-13T11:00:00Z", "end": "2026-10-13T12:00:00Z"}]

    result = await service.availability("tomorrow", "afternoon")

    assert [s.id for s in result.slots] == [
        "2026-10-13T13:30:00+01:00",
        "2026-10-13T14:00:00+01:00",
        "2026-10-13T14:30:00+01:00",
    ]
    assert (
        result.slots[0].say == "Tuesday the thirteenth at one thirty in the afternoon"
    )
    # The day window and the fallback horizon share one freeBusy call.
    assert google.free_busy.call_count == 1


async def test_full_day_widens_to_the_horizon(
    service: CalendarService, google: FakeGoogle
) -> None:
    google.busy = [
        {"start": "2026-10-13T00:00:00+01:00", "end": "2026-10-14T00:00:00+01:00"}
    ]

    result = await service.availability("tuesday", None)

    assert result.slots[0].id == "2026-10-12T09:00:00+01:00"
    assert result.say.startswith("Nothing free then, but I have Monday the twelfth")


async def test_nothing_free_anywhere(
    service: CalendarService, google: FakeGoogle
) -> None:
    google.busy = [{"start": "2026-10-01T00:00:00Z", "end": "2026-11-30T00:00:00Z"}]
    result = await service.availability("tomorrow", None)
    assert result.slots == []
    assert result.say == "I have nothing free in that window."


async def test_weekend_and_custom_rules_come_from_connection_config(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    service = make_service(
        provider,
        http,
        connection_id,
        timezone="America/New_York",
        booking_days=[5],
        open_hour=10,
        close_hour=12,
        slot_minutes=60,
        max_slots_returned=2,
    )
    result = await service.availability(None, None)
    assert [s.id for s in result.slots] == [
        "2026-10-17T10:00:00-04:00",
        "2026-10-17T11:00:00-04:00",
    ]
    assert json_body(google.free_busy.calls.last.request)["timeZone"] == (
        "America/New_York"
    )


# --- booking --------------------------------------------------------------


async def test_book_inserts_event_with_prefix_timezone_and_marker(
    service: CalendarService, google: FakeGoogle, connection_id: uuid.UUID
) -> None:
    result = await service.book(
        "2026-10-12T10:00:00+01:00", "Jane Doe", "0871234567", "New router"
    )

    expected_id = booking_event_id(
        BOOKING_KEY,
        connection_id,
        datetime.fromisoformat("2026-10-12T10:00:00+01:00"),
        "Jane Doe",
        "0871234567",
    )
    assert result.booked is True
    assert result.event_id == expected_id
    assert (
        result.say == "That is booked in for Monday the twelfth at ten in the morning."
    )
    event = json_body(google.insert.calls.last.request)
    assert event == {
        "id": expected_id,
        "summary": "Acme call — Jane Doe",
        "description": (
            "Booked by the Fallcha.ai voice agent.\nCaller: Jane Doe\n"
            "Phone: 0871234567\nReason: New router"
        ),
        "start": {"dateTime": "2026-10-12T10:00:00+01:00", "timeZone": "Europe/Dublin"},
        "end": {"dateTime": "2026-10-12T10:30:00+01:00", "timeZone": "Europe/Dublin"},
        "extendedProperties": {"private": {BOOKING_MARKER: str(connection_id)}},
    }


@pytest.mark.parametrize(
    "slot_id",
    ["2026-10-12T10:00:00", "2026-10-12T09:00:00Z", " 2026-10-12T10:00:00+01:00 "],
)
async def test_book_normalises_slot_to_connection_timezone(
    service: CalendarService, google: FakeGoogle, slot_id: str
) -> None:
    result = await service.book(slot_id, "Jane", "1", None)
    assert result.booked is True
    event = json_body(google.insert.calls.last.request)
    assert event["start"]["dateTime"] == "2026-10-12T10:00:00+01:00"
    assert event["description"].endswith("Reason: not given")


async def test_book_taken_slot_offers_alternatives_without_inserting(
    service: CalendarService, google: FakeGoogle
) -> None:
    google.busy = [{"start": "2026-10-12T09:00:00Z", "end": "2026-10-12T09:30:00Z"}]

    result = await service.book("2026-10-12T10:00:00+01:00", "Jane", "1", None)

    assert result.booked is False
    assert result.slots is not None and len(result.slots) == 3
    assert "2026-10-12T10:00:00+01:00" not in {s.id for s in result.slots}
    assert result.say.startswith("That one has just gone. I have Monday the twelfth")
    assert not google.insert.called


@pytest.mark.parametrize(
    "slot_id",
    [
        "2026-10-12T10:10:00+01:00",  # off the slot grid
        "2026-10-12T06:00:00+01:00",  # in the past
        "2026-10-17T10:00:00+01:00",  # Saturday
    ],
)
async def test_book_rejects_slots_that_were_never_offerable(
    service: CalendarService, google: FakeGoogle, slot_id: str
) -> None:
    result = await service.book(slot_id, "Jane", "1", None)
    assert result.booked is False
    assert not google.insert.called


async def test_book_rejects_garbage_slot_id(
    service: CalendarService, google: FakeGoogle
) -> None:
    with pytest.raises(BadArgumentError, match="ISO timestamp"):
        await service.book("tomorrow at ten", "Jane", "1", None)
    assert not google.free_busy.called


# --- cancel ---------------------------------------------------------------


async def test_cancel_own_booking_once(
    service: CalendarService, google: FakeGoogle
) -> None:
    booked = await service.book("2026-10-12T10:00:00+01:00", "Jane", "1", None)
    assert booked.event_id is not None

    cancelled = await service.cancel(booked.event_id)
    assert cancelled.cancelled is True
    assert cancelled.say == (
        "Your appointment for Monday the twelfth at ten in the morning is cancelled."
    )
    assert google.delete_event.calls.last.request.url.params["sendUpdates"] == "none"

    again = await service.cancel(booked.event_id)
    assert again.cancelled is False
    unknown = await service.cancel("does-not-exist")
    assert unknown.cancelled is False


async def test_cancel_refuses_events_not_booked_by_this_connection(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    service: CalendarService,
    google: FakeGoogle,
) -> None:
    booked = await service.book("2026-10-12T10:00:00+01:00", "Jane", "1", None)
    assert booked.event_id is not None
    google.events["manual"] = {"id": "manual", "status": "confirmed"}

    other = make_service(provider, http, uuid.uuid4())
    assert (await other.cancel(booked.event_id)).cancelled is False
    assert (await service.cancel("manual")).cancelled is False
    assert not google.delete_event.called


# --- order lookup ---------------------------------------------------------


async def test_order_lookup_verifies_name_and_eircode(
    service: CalendarService, google: FakeGoogle
) -> None:
    google.sheet_values = ORDERS

    found = await service.look_up_order("Murphy", "h91x2y3")
    assert found.verified is True
    assert found.order_id == "VT-1"
    assert found.say == (
        "I have your order for the Home Fibre. "
        "The status is: Shipped. Arrives Thursday."
    )

    by_address = await service.look_up_order("John Byrne", "rose cottage kinsale")
    assert by_address.verified is True and by_address.order_id == "VT-2"
    assert by_address.say.endswith("The status is: Pending.")

    wrong_address = await service.look_up_order("Jane Murphy", "Dublin 4")
    unknown_name = await service.look_up_order("Zed Nobody", "H91 X2Y3")
    assert wrong_address.verified is unknown_name.verified is False
    assert wrong_address.say == unknown_name.say
    assert wrong_address.model_dump(exclude_none=True).keys() == {"verified", "say"}

    # Cached for a minute: one sheet read; sheets token is read-only.
    assert google.sheet.call_count == 1
    scopes = {
        _jwt_part(form_body(call.request)["assertion"].split(".")[1])["scope"]
        for call in google.token.calls
    }
    assert scopes == {SHEETS_READONLY_SCOPE}


async def test_order_lookup_tab_is_quoted_and_cache_expires(
    service: CalendarService, google: FakeGoogle, clock: FakeClock
) -> None:
    google.sheet_values = ORDERS
    await service.look_up_order("Murphy", "H91X2Y3")
    assert google.sheet.calls.last.request.url.path.endswith(
        "/values/'Orders'!A1:Z1000"
    )
    clock.advance(timedelta(seconds=61))
    await service.look_up_order("Murphy", "H91X2Y3")
    assert google.sheet.call_count == 2


async def test_order_lookup_needs_a_configured_sheet(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
) -> None:
    service = make_service(provider, http, connection_id)
    with pytest.raises(NotConfiguredError, match="not set up"):
        await service.look_up_order("Murphy", "H91X2Y3")


async def test_empty_or_header_only_sheet(
    service: CalendarService, google: FakeGoogle, clock: FakeClock
) -> None:
    google.sheet_values = []
    with pytest.raises(GoogleApiError, match="empty"):
        await service.look_up_order("Murphy", "H91X2Y3")
    google.sheet_values = ORDERS[:1]
    result = await service.look_up_order("Murphy", "H91X2Y3")
    assert result.verified is False


# --- Google error mapping -------------------------------------------------


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            google_error(403, "forbidden"),
            "the calendar is not accessible; it may not be shared",
        ),
        (google_error(404, "notFound"), "the calendar was not found"),
        (google_error(429, "rateLimitExceeded"), "rate limiting"),
        (google_error(403, "userRateLimitExceeded"), "rate limiting"),
        (google_error(401, "authError"), "rejected the connection's credentials"),
        (google_error(503, "backendError"), "temporarily unavailable"),
        (google_error(400, "badRequest", "secret detail"), "HTTP 400"),
        (httpx.Response(200, text="<html>"), "unreadable"),
    ],
)
async def test_google_errors_become_clear_messages(
    service: CalendarService,
    google: FakeGoogle,
    response: httpx.Response,
    expected: str,
) -> None:
    google.free_busy.mock(return_value=response, side_effect=None)
    with pytest.raises(GoogleApiError) as caught:
        await service.availability(None, None)
    message = str(caught.value)
    assert expected in message
    assert "secret detail" not in message and "ya29" not in message
    assert SA_EMAIL not in message  # callers never learn the Google account


async def test_freebusy_calendar_level_errors(
    service: CalendarService, google: FakeGoogle
) -> None:
    google.free_busy.mock(
        return_value=httpx.Response(
            200,
            json={"calendars": {CALENDAR_ID: {"errors": [{"reason": "notFound"}]}}},
        ),
        side_effect=None,
    )
    with pytest.raises(
        GoogleApiError,
        match=re.escape("the calendar was not found; it may not be shared"),
    ):
        await service.availability(None, None)


async def test_network_timeout_and_deadline(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    service: CalendarService,
    google: FakeGoogle,
) -> None:
    google.free_busy.mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(GoogleApiError, match="did not respond in time"):
        await service.availability(None, None)

    async def stall(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json={})

    google.free_busy.mock(side_effect=stall)
    impatient = dataclasses.replace(provider, deadline_seconds=0.05)
    with pytest.raises(GoogleApiError, match="did not respond in time"):
        await make_service(impatient, http, connection_id).availability(None, None)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            httpx.Response(400, json={"error": "invalid_grant"}),
            "rejected the service-account key",
        ),
        (httpx.Response(429, json={"error": "rate"}), "rate limiting sign-in"),
        (httpx.Response(500, text="oops"), "sign-in failed (HTTP 500)"),
        (httpx.Response(200, json={"nope": 1}), "unreadable sign-in"),
    ],
)
async def test_token_errors(
    service: CalendarService,
    google: FakeGoogle,
    response: httpx.Response,
    expected: str,
) -> None:
    google.token.mock(return_value=response)
    with pytest.raises(GoogleApiError, match=re.escape(expected)) as caught:
        await service.availability(None, None)
    assert "PRIVATE KEY" not in str(caught.value)
    assert not google.free_busy.called


# --- tokens ---------------------------------------------------------------


async def test_token_assertion_is_signed_for_google_only(
    service: CalendarService, google: FakeGoogle
) -> None:
    await service.availability(None, None)

    request = google.token.calls.last.request
    assert str(request.url) == GOOGLE_TOKEN_URL  # never the key's token_uri
    form = form_body(request)
    assert form["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
    header_b64, claims_b64, signature_b64 = form["assertion"].split(".")
    PUBLIC_KEY.verify(
        base64.urlsafe_b64decode(signature_b64 + "=" * (-len(signature_b64) % 4)),
        f"{header_b64}.{claims_b64}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    assert _jwt_part(header_b64) == {"alg": "RS256", "typ": "JWT", "kid": "kid-1"}
    claims = _jwt_part(claims_b64)
    assert claims["iss"] == SA_EMAIL
    assert claims["aud"] == GOOGLE_TOKEN_URL
    assert claims["scope"] == CALENDAR_SCOPE
    assert claims["exp"] - claims["iat"] == 3600


async def test_tokens_are_cached_until_near_expiry(
    service: CalendarService, google: FakeGoogle, clock: FakeClock
) -> None:
    await service.availability(None, None)
    await service.availability("tomorrow", None)
    assert google.token.call_count == 1

    clock.advance(timedelta(minutes=54))  # still > 5 min before expiry
    await service.availability(None, None)
    assert google.token.call_count == 1

    clock.advance(timedelta(minutes=1, seconds=30))  # inside the refresh margin
    await service.availability(None, None)
    assert google.token.call_count == 2


async def test_concurrent_calls_mint_one_token(
    service: CalendarService, google: FakeGoogle
) -> None:
    async def slow_token(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.02)
        return httpx.Response(200, json={"access_token": "ya29.x", "expires_in": 3600})

    google.token.mock(side_effect=slow_token)
    await asyncio.gather(*(service.availability(None, None) for _ in range(5)))
    assert google.token.call_count == 1


async def test_connections_never_share_tokens(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    service: CalendarService,
    google: FakeGoogle,
) -> None:
    await service.availability(None, None)
    await make_service(provider, http, uuid.uuid4()).availability(None, None)
    assert google.token.call_count == 2


# --- wiring ---------------------------------------------------------------


async def test_invalid_stored_config_or_secret_is_reported(
    provider: GoogleCalendarProvider, http: httpx.AsyncClient
) -> None:
    def ctx(**changes: Any) -> ConnectionContext:
        base: dict[str, Any] = {
            "org_id": 1,
            "connection_id": uuid.uuid4(),
            "provider": provider.id,
            "auth_mode": AuthMode.SERVICE_ACCOUNT,
            "secret": service_account_key(),
            "access_token": None,
            "http": http,
            "config": calendar_config(),
        }
        base.update(changes)
        return ConnectionContext(**base)

    with pytest.raises(NotConfiguredError, match="calendar settings"):
        provider.service_for(ctx(config={}))
    with pytest.raises(NotConfiguredError, match="service-account key") as caught:
        provider.service_for(
            ctx(secret={"type": "service_account", "private_key": "x"})
        )
    assert PRIVATE_KEY_PEM not in str(caught.value)
    with pytest.raises(NotConfiguredError, match="not supported"):
        provider.service_for(ctx(auth_mode=AuthMode.API_KEY))
    with pytest.raises(NotConfiguredError, match="not usable"):
        provider.service_for(ctx(auth_mode=AuthMode.OAUTH2))  # no ctx.oauth


# --- review follow-ups: idempotent booking ---------------------------------

SLOT = "2026-10-12T10:00:00+01:00"


async def test_timeout_mid_insert_then_retry_books_once(
    service: CalendarService, google: FakeGoogle
) -> None:
    def lands_then_times_out(request: httpx.Request) -> httpx.Response:
        google._insert(request)  # Google stored it, but the reply was lost
        raise httpx.ReadTimeout("lost reply")

    google.insert.mock(side_effect=lands_then_times_out)
    with pytest.raises(GoogleApiError, match="try booking the same slot again"):
        await service.book(SLOT, "Jane", "087 123", None)
    assert len(google.events) == 1

    google.insert.mock(side_effect=google._insert)
    retried = await service.book(SLOT, "Jane", "087123", None)
    assert retried.booked is True
    assert retried.event_id == next(iter(google.events))
    assert google.insert.call_count == 1  # the retry found its own event
    assert len(google.events) == 1


async def test_duplicate_insert_409_counts_as_booked(
    service: CalendarService, google: FakeGoogle, connection_id: uuid.UUID
) -> None:
    event_id = booking_event_id(
        BOOKING_KEY, connection_id, datetime.fromisoformat(SLOT), "Jane", "087"
    )
    # Created by a racing attempt that free/busy does not show yet.
    google.events[event_id] = {
        "id": event_id,
        "status": "confirmed",
        "extendedProperties": {"private": {BOOKING_MARKER: str(connection_id)}},
    }
    result = await service.book(SLOT, "Jane", "087", None)
    assert result.booked is True and result.event_id == event_id
    assert google.insert.calls.last.response.status_code == 409
    assert not google.patch_event.called


async def test_rebooking_a_cancelled_booking_restores_it(
    service: CalendarService, google: FakeGoogle
) -> None:
    first = await service.book(SLOT, "Jane", "087", None)
    assert first.event_id is not None
    assert (await service.cancel(first.event_id)).cancelled is True

    again = await service.book(SLOT, "Jane", "087", None)
    assert again.booked is True and again.event_id == first.event_id
    assert google.patch_event.called
    assert google.events[first.event_id]["status"] == "confirmed"


async def test_insert_not_started_without_time_left(
    service: CalendarService, google: FakeGoogle
) -> None:
    async def slow_free_busy(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.1)
        return google._free_busy(request)

    google.free_busy.mock(side_effect=slow_free_busy)
    hurried = dataclasses.replace(
        service, deadline_seconds=0.5, min_insert_seconds=0.45
    )
    with pytest.raises(GoogleApiError, match="try booking the same slot again"):
        await hurried.book(SLOT, "Jane", "087", None)
    assert not google.insert.called


async def test_insert_runs_outside_the_deadline_with_remaining_time(
    service: CalendarService, google: FakeGoogle
) -> None:
    async def slow_insert(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.3)  # longer than the deadline has left
        return google._insert(request)

    google.insert.mock(side_effect=slow_insert)
    hurried = dataclasses.replace(
        service, deadline_seconds=0.4, min_insert_seconds=0.05
    )
    result = await hurried.book(SLOT, "Jane", "087", None)
    assert result.booked is True  # not cancelled half way
    read_timeout = google.insert.calls.last.request.extensions["timeout"]["read"]
    assert 0 < read_timeout <= 0.4


# --- review follow-ups: booking window --------------------------------------


@pytest.mark.parametrize(
    ("slot_id", "booked"),
    [
        ("2026-10-12T10:00:00+01:00", False),  # inside the 4h lead time
        ("2026-10-12T11:00:00+01:00", True),
        ("2026-10-23T16:30:00+01:00", True),  # last slot before the horizon
        ("2026-10-26T10:00:00+00:00", False),  # past the 14-day horizon
    ],
)
async def test_book_enforces_lead_time_and_horizon(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
    slot_id: str,
    booked: bool,
) -> None:
    service = make_service(provider, http, connection_id, min_lead_hours=4)
    result = await service.book(slot_id, "Jane", "087", None)
    assert result.booked is booked
    assert google.insert.called is booked


async def test_far_future_date_is_clamped_then_widened(
    service: CalendarService, google: FakeGoogle
) -> None:
    result = await service.availability("2026-12-01", None)
    assert result.say.startswith("Nothing free then, but I have Monday the twelfth")
    for call in google.free_busy.calls:
        assert json_body(call.request)["timeMax"] <= "2026-10-26T07:00:00+00:00"


# --- review follow-ups: credentials and caches ------------------------------


async def test_google_401_invalidates_token_and_retries_once(
    service: CalendarService, google: FakeGoogle
) -> None:
    rejected_once: list[bool] = []

    def revoked_then_ok(request: httpx.Request) -> httpx.Response:
        if not rejected_once:
            rejected_once.append(True)
            return google_error(401, "authError")
        return google._free_busy(request)

    google.free_busy.mock(side_effect=revoked_then_ok)
    result = await service.availability(None, None)
    assert len(result.slots) == 3
    assert google.token.call_count == 2
    assert google.free_busy.call_count == 2

    google.free_busy.mock(side_effect=None, return_value=google_error(401, "authError"))
    with pytest.raises(GoogleApiError, match="rejected the connection's credentials"):
        await service.availability(None, None)
    assert google.free_busy.call_count == 4  # one retry, not a loop


async def test_signer_is_parsed_once_per_connection(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    google: FakeGoogle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parses = 0
    original = ServiceAccountKey.signer

    def counting(self: ServiceAccountKey) -> Any:
        nonlocal parses
        parses += 1
        return original(self)

    monkeypatch.setattr(ServiceAccountKey, "signer", counting)
    for _ in range(3):
        await make_service(provider, http, connection_id).availability(None, None)
    assert parses == 1
    make_service(provider, http, uuid.uuid4())
    assert parses == 2


async def test_token_cache_single_flight_survives_cancelled_waiter(
    clock: FakeClock,
) -> None:
    cache = TokenCache(clock=clock)
    key = (uuid.uuid4(), SA_EMAIL, (CALENDAR_SCOPE,))
    mints = 0

    async def mint() -> CachedToken:
        nonlocal mints
        mints += 1
        await asyncio.sleep(0.05)
        return CachedToken("tok", clock() + timedelta(hours=1))

    first = asyncio.create_task(cache.get_or_mint(key, mint))
    second = asyncio.create_task(cache.get_or_mint(key, mint))
    await asyncio.sleep(0.01)
    first.cancel()
    assert await second == "tok"
    assert mints == 1
    assert cache.minting == 0  # nothing left behind


async def test_token_cache_failed_mint_is_not_sticky(clock: FakeClock) -> None:
    cache = TokenCache(clock=clock)
    key = (uuid.uuid4(), SA_EMAIL, (CALENDAR_SCOPE,))

    async def failing() -> CachedToken:
        raise GoogleApiError("nope")

    async def working() -> CachedToken:
        return CachedToken("tok", clock() + timedelta(hours=1))

    with pytest.raises(GoogleApiError):
        await cache.get_or_mint(key, failing)
    assert cache.minting == 0
    assert await cache.get_or_mint(key, working) == "tok"


async def test_token_cache_is_bounded(clock: FakeClock) -> None:
    cache = TokenCache(clock=clock, max_entries=2)
    for _ in range(5):

        async def mint() -> CachedToken:
            return CachedToken("t", clock() + timedelta(hours=1))

        await cache.get_or_mint((uuid.uuid4(), SA_EMAIL, (CALENDAR_SCOPE,)), mint)
    assert len(cache) == 2


async def test_orders_cache_bounded_and_drops_stale(clock: FakeClock) -> None:
    cache = OrdersCache(max_entries=2)

    async def fetch() -> list[dict[str, str]]:
        return []

    for n in range(3):
        await cache.rows((uuid.uuid4(), f"s{n}", "Orders"), clock(), fetch)
    assert len(cache) == 2
    clock.advance(timedelta(minutes=5))
    await cache.rows((uuid.uuid4(), "fresh", "Orders"), clock(), fetch)
    assert len(cache) == 1


# --- review follow-ups: DST ------------------------------------------------


async def test_slots_and_bookings_across_the_dst_change(
    provider: GoogleCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    clock: FakeClock,
    google: FakeGoogle,
) -> None:
    clock.now = datetime(2026, 10, 23, 14, 0, tzinfo=UTC)  # Fri 15:00 IST
    service = make_service(
        provider, http, connection_id, booking_days=[0, 1, 2, 3, 4, 5, 6]
    )

    sunday = await service.availability("sunday", None)  # Irish clocks go back
    assert sunday.slots[0].id == "2026-10-25T09:00:00+00:00"
    saturday = await service.availability("saturday", None)
    assert saturday.slots[0].id == "2026-10-24T09:00:00+01:00"

    google.busy = [{"start": "2026-10-26T09:00:00Z", "end": "2026-10-26T09:30:00Z"}]
    monday = await service.availability("monday", None)
    assert monday.slots[0].id == "2026-10-26T10:00:00+00:00"
    assert monday.slots[0].say == "Monday the twenty sixth at ten in the morning"

    booked = await service.book(monday.slots[0].id, "Jane", "087", None)
    assert booked.booked is True
    event = json_body(google.insert.calls.last.request)
    assert event["start"] == {
        "dateTime": "2026-10-26T10:00:00+00:00",
        "timeZone": "Europe/Dublin",
    }
    assert event["end"]["dateTime"] == "2026-10-26T10:30:00+00:00"


# --- re-review follow-ups ---------------------------------------------------


def _forget_events_after_409(google: FakeGoogle, *, ids: int) -> None:
    """Google keeps the first ``ids`` ids reserved (409) but cannot read them."""
    reserved: set[str] = set()

    def insert(request: httpx.Request) -> httpx.Response:
        event_id = json_body(request)["id"]
        if len(reserved) < ids and event_id not in reserved:
            reserved.add(event_id)
            return httpx.Response(409, json={"error": {"code": 409}})
        return google._insert(request)

    google.insert.mock(side_effect=insert)


async def test_unreadable_duplicate_falls_back_to_salted_id(
    service: CalendarService, google: FakeGoogle, connection_id: uuid.UUID
) -> None:
    _forget_events_after_409(google, ids=1)
    result = await service.book(SLOT, "Jane", "087", None)

    base = booking_event_id(
        BOOKING_KEY, connection_id, datetime.fromisoformat(SLOT), "Jane", "087"
    )
    assert result.booked is True
    assert result.event_id == base + "v1"
    assert [json_body(c.request)["id"] for c in google.insert.calls] == [
        base,
        base + "v1",
    ]
    # A later retry of the same booking finds the salted event, no third id.
    again = await service.book(SLOT, "Jane", "087", None)
    assert again.booked is True and again.event_id == base + "v1"
    assert google.insert.call_count == 2


async def test_both_ids_unusable_answers_not_available(
    service: CalendarService, google: FakeGoogle
) -> None:
    _forget_events_after_409(google, ids=2)
    result = await service.book(SLOT, "Jane", "087", None)
    assert result.booked is False
    assert result.say.startswith("That one has just gone. I have Monday the twelfth")
    assert google.insert.call_count == 2  # no loop, no "try again"


async def test_confirm_path_uses_the_remaining_budget(
    service: CalendarService, google: FakeGoogle, connection_id: uuid.UUID
) -> None:
    event_id = booking_event_id(
        BOOKING_KEY, connection_id, datetime.fromisoformat(SLOT), "Jane", "087"
    )
    google.events[event_id] = {
        "id": event_id,
        "status": "cancelled",
        "extendedProperties": {"private": {BOOKING_MARKER: str(connection_id)}},
    }
    hurried = dataclasses.replace(service, deadline_seconds=0.6, min_insert_seconds=0.1)
    result = await hurried.book(SLOT, "Jane", "087", None)
    assert result.booked is True and result.event_id == event_id
    for route in (google.insert, google.get_event, google.patch_event):
        read = route.calls.last.request.extensions["timeout"]["read"]
        assert 0 < read <= 0.6


async def test_low_budget_skips_401_retry_and_token_mint(
    service: CalendarService, google: FakeGoogle
) -> None:
    async def slow_unauthorised_insert(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.25)  # eats the budget, then says 401
        return google_error(401, "authError")

    google.insert.mock(side_effect=slow_unauthorised_insert)
    hurried = dataclasses.replace(service, deadline_seconds=0.4, min_insert_seconds=0.2)
    with pytest.raises(GoogleApiError, match="rejected the connection's credentials"):
        await hurried.book(SLOT, "Jane", "087", None)
    assert google.insert.call_count == 1
    assert google.token.call_count == 1  # no second mint was started


def test_booking_ids_are_keyed_and_deterministic(connection_id: uuid.UUID) -> None:
    slot = datetime.fromisoformat(SLOT)
    first = booking_event_id(BOOKING_KEY, connection_id, slot, "Jane", "087 1")
    assert first == booking_event_id(BOOKING_KEY, connection_id, slot, " jane", "0871")
    assert first != booking_event_id(
        b"another-key", connection_id, slot, "Jane", "0871"
    )
    assert set(first) <= set("0123456789abcdefghijklmnopqrstuv")  # base32hex
    assert 5 <= len(first) <= 1024
