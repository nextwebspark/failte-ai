"""Outlook Calendar: Microsoft sign-in, and Google Calendar's booking service
on a respx-mocked Microsoft Graph."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx
from pydantic import JsonValue, SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from fallcha_tools.config import Settings
from fallcha_tools.core.models import AuthMode
from fallcha_tools.core.provider import ConnectionContext, ProviderRegistry
from fallcha_tools.core.repositories import platform_app_id
from fallcha_tools.providers import build_registry, platform_clients
from fallcha_tools.providers.google_calendar.credentials import TokenCache
from fallcha_tools.providers.google_calendar.errors import GoogleApiError
from fallcha_tools.providers.google_calendar.matching import PHONE_KEY_PROPERTY
from fallcha_tools.providers.google_calendar.schemas import RescheduleOutcome
from fallcha_tools.providers.google_calendar.service import (
    BOOKING_MARKER,
    CalendarService,
    booking_event_id,
)
from fallcha_tools.providers.outlook_calendar import (
    MICROSOFT_FAMILY,
    OutlookCalendarProvider,
)
from fallcha_tools.providers.outlook_calendar.graph import (
    BOOKING_ID_PROP,
    property_id,
)
from tests.conftest import INTERNAL_SECRET, TEST_DATABASE_URL, internal_headers
from tests.google_fakes import BOOKING_KEY, FakeClock, form_body, json_body
from tests.graph_fakes import ME, FakeGraph, FakeTokens

PROVIDER = "outlook-calendar"
MS_ID = "11111111-2222-3333-4444-555555555555"
MS_SECRET = "ms~client-secret-must-never-leak"
MS_APP_ID = platform_app_id(MICROSOFT_FAMILY, MS_ID)
PUBLIC_BASE = "https://tools.fallcha.test/tools"
UI_RETURN = "https://app.fallcha.test/integrations"
LOGIN = "https://login.microsoftonline.com/common/oauth2/v2.0"
EMAIL = "alice@contoso.test"
REFRESH_TOKEN = "M.R3_refresh-token-must-never-leak"
# Monday 2026-10-12, 07:00 in Dublin (IST, UTC+1).
MONDAY = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
# Monday 2026-10-26, 07:00 in Dublin (GMT, UTC+0: summer time is over).
WINTER_MONDAY = datetime(2026, 10, 26, 7, 0, tzinfo=UTC)
NAME, PHONE = "Mary Byrne", "087 123 4567"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(MONDAY)


@pytest.fixture
def provider(clock: FakeClock) -> OutlookCalendarProvider:
    return OutlookCalendarProvider(
        booking_id_key=BOOKING_KEY, token_cache=TokenCache(clock=clock), clock=clock
    )


@pytest.fixture
def graph(clock: FakeClock) -> Iterator[FakeGraph]:
    with respx.mock(assert_all_called=False) as router:
        yield FakeGraph(router, now=clock.now)


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def tokens() -> FakeTokens:
    return FakeTokens()


@pytest.fixture
def connection_id() -> uuid.UUID:
    return uuid.uuid4()


def context(
    provider: OutlookCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    tokens: FakeTokens,
    **config: JsonValue,
) -> ConnectionContext:
    return ConnectionContext(
        org_id=1,
        connection_id=connection_id,
        provider=PROVIDER,
        auth_mode=AuthMode.OAUTH2,
        secret={},
        access_token=None,
        http=http,
        config={"calendar_id": "primary", "timezone": "Europe/Dublin", **config},
        account_label=EMAIL,
        scopes_granted=("Calendars.ReadWrite", "User.Read"),
        oauth=tokens,
    )


@pytest.fixture
def make_service(
    provider: OutlookCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    tokens: FakeTokens,
) -> Any:
    def make(**config: JsonValue) -> CalendarService:
        return provider.service_for(
            context(provider, http, connection_id, tokens, **config)
        )

    return make


# --- free slots ----------------------------------------------------------------


async def test_free_slots_are_offered_in_dublin_time(
    make_service: Any, graph: FakeGraph, tokens: FakeTokens
) -> None:
    result = await make_service().availability(None, None)

    assert [s.id for s in result.slots] == [
        "2026-10-12T09:00:00+01:00",
        "2026-10-12T09:30:00+01:00",
        "2026-10-12T10:00:00+01:00",
    ]
    request = graph.view.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {tokens.token}"
    assert 'outlook.timezone="UTC"' in request.headers.get_list("Prefer")
    assert request.url.params["startDateTime"].endswith("+00:00")


async def test_busy_events_block_their_time_but_free_ones_do_not(
    make_service: Any, graph: FakeGraph
) -> None:
    # 09:00-10:00 Dublin summer time is 08:00-09:00 UTC.
    graph.add(
        datetime(2026, 10, 12, 8, 0, tzinfo=UTC),
        datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
    )
    graph.add(
        datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
        datetime(2026, 10, 12, 10, 0, tzinfo=UTC),
        subject="Lunch reminder",
        show_as="free",
    )

    result = await make_service().availability(None, None)

    # The meeting plus the 15-minute buffer closes 10:00; the event shown
    # as Free (10:00-11:00 Dublin) closes nothing.
    assert [s.id for s in result.slots] == [
        "2026-10-12T10:30:00+01:00",
        "2026-10-12T11:00:00+01:00",
        "2026-10-12T11:30:00+01:00",
    ]


async def test_winter_time_slots_use_gmt(
    make_service: Any, graph: FakeGraph, clock: FakeClock
) -> None:
    clock.now = WINTER_MONDAY
    graph.add(
        datetime(2026, 10, 26, 9, 0, tzinfo=UTC),
        datetime(2026, 10, 26, 9, 30, tzinfo=UTC),
    )

    result = await make_service().availability(None, None)

    assert result.slots[0].id == "2026-10-26T10:00:00+00:00"


# --- book, find, move, cancel ---------------------------------------------------


async def book(
    service: CalendarService, slot: str = "2026-10-12T10:00:00+01:00"
) -> str:
    result = await service.book(slot, NAME, PHONE, "check-up")
    assert result.booked, result
    assert result.event_id is not None
    return result.event_id


async def test_booking_creates_a_utc_event_tagged_with_its_booking_id(
    make_service: Any, graph: FakeGraph, connection_id: uuid.UUID
) -> None:
    event_id = await book(make_service())

    slot = datetime.fromisoformat("2026-10-12T10:00:00+01:00")
    assert event_id == booking_event_id(BOOKING_KEY, connection_id, slot, NAME, PHONE)
    sent = json_body(graph.insert.calls.last.request)
    assert sent["start"] == {"dateTime": "2026-10-12T09:00:00", "timeZone": "UTC"}
    assert sent["end"] == {"dateTime": "2026-10-12T09:30:00", "timeZone": "UTC"}
    assert sent["body"]["contentType"] == "text"
    assert f"Caller: {NAME}" in sent["body"]["content"]
    props = {p["id"]: p["value"] for p in sent["singleValueExtendedProperties"]}
    assert props[property_id(BOOKING_ID_PROP)] == event_id
    assert props[property_id(BOOKING_MARKER)] == str(connection_id)
    assert props[property_id(PHONE_KEY_PROPERTY)] == "71234567"


async def test_a_retried_booking_is_not_made_twice(
    make_service: Any, graph: FakeGraph
) -> None:
    service = make_service()
    first = await book(service)
    second = await book(service)

    assert first == second
    assert graph.insert.call_count == 1
    assert len(graph.ours()) == 1


async def test_find_move_and_cancel_a_booking(
    make_service: Any, graph: FakeGraph
) -> None:
    service = make_service(ai_changes_enabled=True)
    event_id = await book(service)

    found = await service.find(caller_phone="0871234567", caller_name="Byrne")
    assert [a.event_id for a in found.appointments] == [event_id]
    # The caller's bookings are asked for by phone key, not read page by page.
    searched = graph.search.calls.last.request.url.params["$filter"]
    assert PHONE_KEY_PROPERTY in searched

    moved = await service.reschedule(event_id, "2026-10-12T11:00:00+01:00")
    assert moved.outcome == RescheduleOutcome.MOVED, moved
    assert moved.event_id is not None and moved.event_id != event_id
    [left] = graph.ours()
    assert left["start"]["dateTime"].startswith("2026-10-12T10:00:00")

    cancelled = await service.cancel(moved.event_id)
    assert cancelled.cancelled, cancelled
    assert cancelled.starts_at == "2026-10-12T11:00:00+01:00"
    assert graph.ours() == []
    assert graph.delete.call_count == 2


async def test_cancelling_an_unknown_booking_touches_nothing(
    make_service: Any, graph: FakeGraph
) -> None:
    result = await make_service(ai_changes_enabled=True).cancel("not-a-booking")

    assert not result.cancelled
    assert graph.delete.call_count == 0


async def test_bookings_list_reads_the_caller_details(
    provider: OutlookCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    tokens: FakeTokens,
    make_service: Any,
    graph: FakeGraph,
) -> None:
    event_id = await book(make_service())
    graph.add(
        datetime(2026, 10, 12, 12, 0, tzinfo=UTC),
        datetime(2026, 10, 12, 13, 0, tzinfo=UTC),
    )

    bookings = await provider.list_bookings(
        context(provider, http, connection_id, tokens),
        datetime(2026, 10, 12, tzinfo=UTC),
        datetime(2026, 10, 13, tzinfo=UTC),
    )

    [booking] = bookings
    assert booking.event_id == event_id
    assert (booking.caller_name, booking.caller_phone) == (NAME, PHONE)
    assert booking.reason == "check-up"
    assert booking.status == "confirmed"


# --- access and errors -----------------------------------------------------------


async def test_connection_test_names_the_calendar(
    provider: OutlookCalendarProvider,
    http: httpx.AsyncClient,
    connection_id: uuid.UUID,
    tokens: FakeTokens,
    graph: FakeGraph,
) -> None:
    result = await provider.test_connection(
        context(provider, http, connection_id, tokens)
    )
    assert result.ok, result
    assert result.message == "Calendar 'Calendar' is reachable"
    assert result.account_label == EMAIL


async def test_a_refused_token_is_replaced_once(
    make_service: Any, graph: FakeGraph, tokens: FakeTokens
) -> None:
    graph.calendar.side_effect = [
        httpx.Response(401, json={"error": {"code": "InvalidAuthenticationToken"}}),
        httpx.Response(200, json={"name": "Calendar"}),
    ]
    first = tokens.token

    assert await make_service().check_access() == "Calendar 'Calendar' is reachable"

    sent = [c.request.headers["Authorization"] for c in graph.calendar.calls]
    assert sent == [f"Bearer {first}", f"Bearer {first}-new"]


async def test_graph_failures_are_speakable(
    make_service: Any, graph: FakeGraph
) -> None:
    graph.view.side_effect = None
    graph.view.return_value = httpx.Response(
        503, json={"error": {"code": "ServiceUnavailable", "message": "secret"}}
    )

    with pytest.raises(GoogleApiError, match="Microsoft is temporarily unavailable"):
        await make_service().availability(None, None)


async def test_a_connection_without_oauth_is_not_usable(
    provider: OutlookCalendarProvider, http: httpx.AsyncClient
) -> None:
    ctx = ConnectionContext(
        org_id=1,
        connection_id=uuid.uuid4(),
        provider=PROVIDER,
        auth_mode=AuthMode.OAUTH2,
        secret={},
        access_token=None,
        http=http,
        config={"calendar_id": "primary"},
    )
    result = await provider.test_connection(ctx)
    assert not result.ok
    assert "not usable" in result.message


# --- settings: unconfigured deployments ------------------------------------------


def base_settings(**extra: str) -> Settings:
    values: dict[str, Any] = {
        "DATABASE_URL": TEST_DATABASE_URL,
        "TOOLS_ENCRYPTION_KEYS": "x" * 44,
        "TOOLS_INTERNAL_SECRET": INTERNAL_SECRET,
        "TOOLS_GOOGLE_CLIENT_ID": "",
        "TOOLS_GOOGLE_CLIENT_SECRET": "",
        "TOOLS_MICROSOFT_CLIENT_ID": "",
        "TOOLS_MICROSOFT_CLIENT_SECRET": "",
        **extra,
    }
    return Settings(**values)


def test_outlook_is_not_offered_without_a_microsoft_client() -> None:
    settings = base_settings()
    assert PROVIDER not in [p.id for p in build_registry(settings)]
    assert platform_clients(settings) == []


def test_outlook_is_offered_with_a_microsoft_client() -> None:
    settings = base_settings(
        TOOLS_MICROSOFT_CLIENT_ID=MS_ID,
        TOOLS_MICROSOFT_CLIENT_SECRET=MS_SECRET,
        TOOLS_MICROSOFT_TENANT="contoso.onmicrosoft.com",
    )
    provider = build_registry(settings).get(PROVIDER)
    assert isinstance(provider, OutlookCalendarProvider)
    assert provider.oauth.authorize_url == (
        "https://login.microsoftonline.com/contoso.onmicrosoft.com"
        "/oauth2/v2.0/authorize"
    )
    [client] = platform_clients(settings)
    assert (client.family, client.client_id) == (MICROSOFT_FAMILY, MS_ID)
    assert MS_SECRET not in repr(client)


@pytest.mark.parametrize(
    "extra",
    [
        {"TOOLS_MICROSOFT_CLIENT_ID": MS_ID},
        {"TOOLS_MICROSOFT_CLIENT_SECRET": MS_SECRET},
        {
            "TOOLS_MICROSOFT_CLIENT_ID": MS_ID,
            "TOOLS_MICROSOFT_CLIENT_SECRET": MS_SECRET,
            "TOOLS_MICROSOFT_TENANT": "../evil",
        },
    ],
)
def test_microsoft_settings_are_checked(extra: dict[str, str]) -> None:
    with pytest.raises(ValidationError) as raised:
        base_settings(**extra)
    assert MS_SECRET not in str(raised.value)


def test_blank_tenant_means_common() -> None:
    assert base_settings(TOOLS_MICROSOFT_TENANT=" ").microsoft_tenant == "common"


# --- signing in with Microsoft (through the app) ----------------------------------


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "public_base_url": PUBLIC_BASE,
            "ui_return_url": UI_RETURN,
            "microsoft_client_id": MS_ID,
            "microsoft_client_secret": SecretStr(MS_SECRET),
        }
    )


@pytest.fixture
def registry(clock: FakeClock) -> ProviderRegistry:
    return ProviderRegistry(
        [OutlookCalendarProvider(booking_id_key=BOOKING_KEY, clock=clock)]
    )


@pytest.fixture
def microsoft(graph: FakeGraph) -> respx.Route:
    graph.router.get(f"{ME}").respond(
        json={"mail": None, "userPrincipalName": EMAIL, "displayName": "Alice"}
    )
    return graph.router.post(f"{LOGIN}/token").respond(
        json={
            "access_token": "EwB-first",
            "refresh_token": REFRESH_TOKEN,
            "expires_in": 3599,
            "token_type": "Bearer",
            # Microsoft may name Graph scopes with their resource.
            "scope": "https://graph.microsoft.com/Calendars.ReadWrite "
            "https://graph.microsoft.com/User.Read",
        }
    )


async def start_sign_in(client: httpx.AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/internal/oauth/start",
        headers=internal_headers(user_id=42),
        json={"provider": PROVIDER, "provider_app_id": str(MS_APP_ID)},
    )
    assert response.status_code == 200, response.text
    url = urlsplit(response.json()["authorization_url"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == f"{LOGIN}/authorize"
    params = {k: v[0] for k, v in parse_qs(url.query).items()}
    params["browser_nonce"] = response.json()["browser_nonce"]
    return params


async def finish_sign_in(client: httpx.AsyncClient, params: dict[str, str]) -> str:
    response = await client.get(
        f"/oauth/{PROVIDER}/callback",
        params={"state": params["state"], "code": "ms-auth-code"},
    )
    assert response.status_code == 302, response.text
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["integration_result"] == ["success"], query
    connection_id = query["connection_id"][0]
    confirmed = await client.post(
        f"/internal/connections/{connection_id}/confirm",
        headers=internal_headers(user_id=42),
        json={"browser_nonce": params["browser_nonce"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    return connection_id


async def test_catalog_and_platform_client(client: httpx.AsyncClient) -> None:
    catalog = await client.get("/internal/catalog", headers=internal_headers())
    [entry] = catalog.json()["providers"]
    assert entry["id"] == PROVIDER and entry["auth_family"] == MICROSOFT_FAMILY
    assert entry["auth_modes"] == ["oauth2"]
    assert "bookings" in entry["capabilities"]
    assert {tool["name"] for tool in entry["tools"]} == {
        "check_appointment_availability",
        "book_appointment",
        "cancel_appointment",
        "find_appointments",
        "reschedule_appointment",
    }
    assert entry["oauth"]["redirect_uri"] == f"{PUBLIC_BASE}/oauth/{PROVIDER}/callback"

    apps = await client.get("/internal/provider-apps", headers=internal_headers())
    assert MS_SECRET not in apps.text
    [app] = apps.json()["provider_apps"]
    assert (app["id"], app["provider"], app["managed"]) == (
        str(MS_APP_ID),
        MICROSOFT_FAMILY,
        True,
    )


async def test_connect_callback_and_refresh(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    graph: FakeGraph,
    microsoft: respx.Route,
) -> None:
    params = await start_sign_in(client)
    assert params["client_id"] == MS_ID
    assert params["scope"] == "offline_access Calendars.ReadWrite User.Read"
    assert params["redirect_uri"] == f"{PUBLIC_BASE}/oauth/{PROVIDER}/callback"
    assert params["code_challenge_method"] == "S256"
    assert params["prompt"] == "select_account"

    connection_id = await finish_sign_in(client, params)

    exchanged = form_body(microsoft.calls.last.request)
    assert exchanged["grant_type"] == "authorization_code"
    assert (exchanged["client_id"], exchanged["client_secret"]) == (MS_ID, MS_SECRET)
    assert exchanged["code"] == "ms-auth-code" and exchanged["code_verifier"]
    listed = await client.get(
        f"/internal/connections/{connection_id}", headers=internal_headers()
    )
    body = listed.json()
    assert body["account_label"] == EMAIL
    assert body["scopes_granted"] == ["Calendars.ReadWrite", "User.Read"]
    assert body["config"]["calendar_id"] == "primary"
    assert REFRESH_TOKEN not in listed.text

    # The access token runs out: the next call refreshes it with Microsoft.
    from tests.test_oauth import expire_access_token

    await expire_access_token(engine, connection_id)
    microsoft.respond(json={"access_token": "EwB-refreshed", "expires_in": 3599})
    tested = await client.post(
        f"/internal/connections/{connection_id}/test", headers=internal_headers()
    )
    assert tested.json()["ok"] is True, tested.text
    assert form_body(microsoft.calls.last.request) == {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": MS_ID,
        "client_secret": MS_SECRET,
    }
    sent = graph.calendar.calls.last.request.headers["Authorization"]
    assert sent == "Bearer EwB-refreshed"


async def test_a_refused_permission_is_reported(
    client: httpx.AsyncClient, microsoft: respx.Route
) -> None:
    microsoft.respond(
        json={
            "access_token": "EwB-first",
            "refresh_token": REFRESH_TOKEN,
            "expires_in": 3599,
            "scope": "User.Read",
        }
    )
    params = await start_sign_in(client)
    response = await client.get(
        f"/oauth/{PROVIDER}/callback",
        params={"state": params["state"], "code": "ms-auth-code"},
    )
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query == {"integration_result": ["error"], "reason": ["scopes_missing"]}
