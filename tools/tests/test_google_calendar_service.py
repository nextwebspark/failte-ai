"""Calendar service, client and credentials against a respx-mocked Google."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
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
    TokenCache,
)
from fallcha_tools.providers.google_calendar.errors import (
    BadArgumentError,
    GoogleApiError,
    NotConfiguredError,
)
from fallcha_tools.providers.google_calendar.service import (
    BOOKING_MARKER,
    CalendarService,
)
from tests.google_fakes import (
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
    return GoogleCalendarProvider(token_cache=TokenCache(clock=clock), clock=clock)


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

    assert result.booked is True
    assert result.event_id == "evt1"
    assert (
        result.say == "That is booked in for Monday the twelfth at ten in the morning."
    )
    event = json_body(google.insert.calls.last.request)
    assert event == {
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
            f"not accessible; make sure it is shared with {SA_EMAIL}",
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
        match=re.escape(f"was not found; make sure it is shared with {SA_EMAIL}"),
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
    impatient = GoogleCalendarProvider(
        token_cache=provider.token_cache, clock=provider.clock, deadline_seconds=0.05
    )
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
        provider.service_for(ctx(auth_mode=AuthMode.OAUTH2))
