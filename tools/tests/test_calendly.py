"""Calendly provider against a respx-mocked Calendly API (no database).

Runs without the suite's database fixtures:
``pytest --noconftest tests/test_calendly.py``.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastmcp import FastMCP
from pydantic import JsonValue, ValidationError

from fallcha_tools.core.errors import InvalidRequestError
from fallcha_tools.core.models import AuthMode
from fallcha_tools.core.provider import (
    AccessToken,
    BookingListFailed,
    ConfigChoicesProvider,
    ConnectionContext,
    SecretCheckingProvider,
    provider_capabilities,
)
from fallcha_tools.providers.calendly import CalendlyProvider
from fallcha_tools.providers.calendly.provider import TOKEN_REJECTED
from fallcha_tools.providers.calendly.settings import CalendlyConfig

API = "https://api.calendly.com"
TOKEN = "calendly-personal-access-token-0123456789"
EVENT_TYPE_UUID = "ET-1111"
EVENT_TYPE = f"{API}/event_types/{EVENT_TYPE_UUID}"
USER = f"{API}/users/U-1"
CONNECTION_ID = uuid.UUID("6f1c3c56-8b0e-4b8f-9a7c-0d2c1e9a5b11")
# Monday 2026-10-12, 07:00 in Dublin (IST, UTC+1).
NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)


def config(**overrides: JsonValue) -> dict[str, JsonValue]:
    base: dict[str, JsonValue] = {
        "event_type": EVENT_TYPE,
        "event_type_name": "Consultation",
        "timezone": "Europe/Dublin",
    }
    base.update(overrides)
    return base


@dataclass
class FakeOAuth:
    tokens: list[str]
    rejected_seen: list[str | None] = field(default_factory=list)

    async def access_token(self, *, rejected: str | None = None) -> AccessToken:
        self.rejected_seen.append(rejected)
        if rejected is not None and self.tokens and self.tokens[0] == rejected:
            self.tokens.pop(0)
        return AccessToken(self.tokens[0], NOW + timedelta(hours=1))


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def calendly() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=API, assert_all_called=False) as router:
        router.get("/users/me").respond(
            200,
            json={
                "resource": {
                    "uri": USER,
                    "name": "Aoife Byrne",
                    "email": "aoife@example.ie",
                    "timezone": "Europe/Dublin",
                }
            },
        )
        yield router


def provider() -> CalendlyProvider:
    return CalendlyProvider(clock=lambda: NOW)


def ctx(
    http: httpx.AsyncClient,
    *,
    cfg: dict[str, JsonValue] | None = None,
    oauth: FakeOAuth | None = None,
    contact_phone: str | None = None,
) -> ConnectionContext:
    return ConnectionContext(
        org_id=7,
        connection_id=CONNECTION_ID,
        provider="calendly",
        auth_mode=AuthMode.OAUTH2 if oauth else AuthMode.API_KEY,
        secret={} if oauth else {"token": TOKEN},
        access_token=None,
        http=http,
        config=config() if cfg is None else cfg,
        oauth=oauth,
        contact_phone=contact_phone,
    )


def times(*starts: str) -> dict[str, Any]:
    return {
        "collection": [
            {
                "status": "available",
                "invitees_remaining": 1,
                "start_time": start,
                "scheduling_url": "https://calendly.com/acme/consult",
            }
            for start in starts
        ]
    }


def event_type(**overrides: Any) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "uri": EVENT_TYPE,
        "name": "Consultation",
        "active": True,
        "duration": 30,
        "kind": "solo",
        "pooling_type": None,
        "locations": [{"kind": "outbound_call"}],
        "custom_questions": [
            {
                "name": "Phone number",
                "type": "phone_number",
                "position": 0,
                "enabled": True,
                "required": True,
                "answer_choices": [],
                "include_other": False,
            },
            {
                "name": "Please share anything that will help prepare",
                "type": "text",
                "position": 1,
                "enabled": True,
                "required": False,
                "answer_choices": [],
                "include_other": False,
            },
        ],
    }
    resource.update(overrides)
    return resource


def query(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(str(request.url)).query).items()}


# -- catalog shape -------------------------------------------------------------


def test_capabilities_and_auth_modes() -> None:
    p = provider()
    assert set(provider_capabilities(p)) == {"bookings", "choices"}
    assert isinstance(p, SecretCheckingProvider)
    assert isinstance(p, ConfigChoicesProvider)
    assert p.auth_modes == {AuthMode.API_KEY, AuthMode.OAUTH2}
    assert "scheduled_events:write" in p.oauth.scopes


async def test_tool_names_match_google_calendar() -> None:
    mcp: FastMCP[Any] = FastMCP("calendly")

    async def factory() -> ConnectionContext:
        raise AssertionError("not called")

    provider().register_tools(mcp, factory)
    names = {tool.name for tool in await mcp.list_tools(run_middleware=False)}
    assert names == {"check_appointment_availability", "book_appointment"}


def test_event_type_must_be_on_calendly_api_host() -> None:
    with pytest.raises(ValidationError):
        CalendlyConfig.model_validate(
            {"event_type": "https://evil.example/event_types/X"}
        )
    assert CalendlyConfig.model_validate({}).event_type is None


# -- token check on save -----------------------------------------------------------


async def test_new_token_is_checked_with_users_me(
    http: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    label = await provider().check_new_secret(http, AuthMode.API_KEY, {"token": TOKEN})
    assert label == "aoife@example.ie"
    request = calendly.routes[0].calls.last.request
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"


async def test_rejected_token_is_refused_without_echoing_it(
    http: httpx.AsyncClient,
) -> None:
    with respx.mock(base_url=API) as router:
        router.get("/users/me").respond(401, json={"title": "Unauthenticated"})
        with pytest.raises(InvalidRequestError) as caught:
            await provider().check_new_secret(http, AuthMode.API_KEY, {"token": TOKEN})
    assert str(caught.value) == TOKEN_REJECTED
    assert TOKEN not in str(caught.value)


def test_malformed_token_is_refused_without_a_call() -> None:
    with pytest.raises(InvalidRequestError):
        provider().validate_secret(AuthMode.API_KEY, {"token": "short"})


# -- free times --------------------------------------------------------------------


async def test_availability_reads_calendly_free_times(
    http: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    route = calendly.get("/event_type_available_times").respond(
        200, json=times("2026-10-13T08:00:00.000000Z", "2026-10-13T13:30:00.000000Z")
    )
    result = await provider().service_for(ctx(http)).availability("tomorrow", None)
    assert [s.id for s in result.slots] == [
        "2026-10-13T09:00:00+01:00",
        "2026-10-13T14:30:00+01:00",
    ]
    assert result.say.startswith("I have Tuesday the thirteenth at nine")
    assert result.handoff is None
    params = query(route.calls[0].request)
    assert params["event_type"] == EVENT_TYPE
    assert params["start_time"] == "2026-10-12T23:00:00Z"
    assert params["end_time"] == "2026-10-13T23:00:00Z"


async def test_availability_filters_part_of_day_and_widens(
    http: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    calendly.get("/event_type_available_times").respond(
        200, json=times("2026-10-13T08:00:00Z", "2026-10-15T14:00:00Z")
    )
    service = provider().service_for(ctx(http))
    afternoon = await service.availability(None, "afternoon")
    assert [s.id for s in afternoon.slots] == ["2026-10-15T15:00:00+01:00"]
    # Nothing on Wednesday: other days are offered, never a dead end.
    wider = await service.availability("wednesday", None)
    assert wider.say.startswith("Nothing free then, but")
    assert len(wider.slots) == 2


async def test_long_searches_are_split_into_week_long_requests(
    http: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    route = calendly.get("/event_type_available_times").respond(200, json=times())
    result = (
        await provider()
        .service_for(ctx(http, cfg=config(horizon_days=20)))
        .availability(None, None)
    )
    assert result.handoff == "fully_booked"
    for call in route.calls:
        params = query(call.request)
        start = datetime.fromisoformat(params["start_time"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(params["end_time"].replace("Z", "+00:00"))
        assert timedelta(0) < end - start <= timedelta(days=7)
        assert start > NOW


async def test_no_event_type_or_booking_off_hands_off_without_calling(
    http: httpx.AsyncClient,
) -> None:
    with respx.mock(base_url=API) as router:
        unset = provider().service_for(ctx(http, cfg={"timezone": "Europe/Dublin"}))
        assert (await unset.availability(None, None)).handoff == "not_set_up"
        off = provider().service_for(ctx(http, cfg=config(ai_booking_enabled=False)))
        assert (await off.availability(None, None)).handoff == "booking_off"
        booked = await off.book("2026-10-13T09:00:00+01:00", "Mary", "m@example.ie")
        assert booked.booked is False and booked.handoff == "booking_off"
        assert not router.calls


async def test_account_time_zone_is_used_when_none_is_set(
    http: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    calendly.get("/event_type_available_times").respond(
        200, json=times("2026-10-13T08:00:00Z")
    )
    result = (
        await provider()
        .service_for(ctx(http, cfg=config(timezone=None)))
        .availability("tomorrow", None)
    )
    assert [s.id for s in result.slots] == ["2026-10-13T09:00:00+01:00"]


# -- booking -----------------------------------------------------------------------


async def test_book_creates_a_real_calendly_booking(
    http: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    calendly.get(f"/event_types/{EVENT_TYPE_UUID}").respond(
        200, json={"resource": event_type()}
    )
    post = calendly.post("/invitees").respond(
        201,
        json={
            "resource": {
                "uri": f"{API}/scheduled_events/EV-9/invitees/INV-1",
                "event": f"{API}/scheduled_events/EV-9",
                "status": "active",
            }
        },
    )
    result = (
        await provider()
        .service_for(ctx(http))
        .book(
            "2026-10-13T09:00:00+01:00",
            "Mary Byrne",
            "mary@example.ie",
            "087 123 4567",
            "Knee pain",
        )
    )
    assert result.booked is True
    assert result.event_id == "EV-9"
    assert result.starts_at == "2026-10-13T09:00:00+01:00"
    assert "Calendly will email" in result.say
    body = json.loads(post.calls[0].request.content)
    assert body["event_type"] == EVENT_TYPE
    assert body["start_time"] == "2026-10-13T08:00:00Z"
    assert body["invitee"] == {
        "name": "Mary Byrne",
        "email": "mary@example.ie",
        "timezone": "Europe/Dublin",
    }
    assert body["location"] == {"kind": "outbound_call", "location": "+353871234567"}
    assert body["questions_and_answers"] == [
        {"question": "Phone number", "answer": "+353871234567", "position": 0},
        {
            "question": "Please share anything that will help prepare",
            "answer": "Knee pain",
            "position": 1,
        },
    ]
    assert body["tracking"]["utm_source"] == "lightmove-ai"
    assert body["tracking"]["utm_content"] == str(CONNECTION_ID)
    assert post.calls[0].request.headers["Authorization"] == f"Bearer {TOKEN}"


async def test_book_uses_the_call_number_for_a_phone_appointment(
    http: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    calendly.get(f"/event_types/{EVENT_TYPE_UUID}").respond(
        200, json={"resource": event_type(custom_questions=[])}
    )
    post = calendly.post("/invitees").respond(
        201, json={"resource": {"event": f"{API}/scheduled_events/EV-2"}}
    )
    service = provider().service_for(ctx(http, contact_phone="+353 87 765 4321"))
    result = await service.book("2026-10-13T09:00:00+01:00", "Mary", "mary@example.ie")
    assert result.booked is True
    body = json.loads(post.calls[0].request.content)
    assert body["location"]["location"] == "+353877654321"


async def test_phone_appointment_without_a_number_asks_for_one(
    http: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    calendly.get(f"/event_types/{EVENT_TYPE_UUID}").respond(
        200, json={"resource": event_type(custom_questions=[])}
    )
    post = calendly.post("/invitees")
    result = (
        await provider()
        .service_for(ctx(http))
        .book("2026-10-13T09:00:00+01:00", "Mary", "mary@example.ie")
    )
    assert result.booked is False and result.handoff is None
    assert "number" in result.say
    assert not post.called


async def test_free_plan_is_reported_not_faked(
    http: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    calendly.get(f"/event_types/{EVENT_TYPE_UUID}").respond(
        200, json={"resource": event_type(locations=[], custom_questions=[])}
    )
    calendly.post("/invitees").respond(
        403,
        json={
            "title": "Permission Denied",
            "message": "Please upgrade to a paid Calendly account.",
        },
    )
    result = (
        await provider()
        .service_for(ctx(http))
        .book("2026-10-13T09:00:00+01:00", "Mary", "mary@example.ie")
    )
    assert result.booked is False
    assert result.handoff == "plan_required"
    assert result.event_id is None


async def test_taken_time_offers_others(
    http: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    calendly.get(f"/event_types/{EVENT_TYPE_UUID}").respond(
        200, json={"resource": event_type(locations=None, custom_questions=[])}
    )
    calendly.post("/invitees").respond(
        400,
        json={
            "title": "Invalid Argument",
            "message": "The selected time is unavailable",
        },
    )
    calendly.get("/event_type_available_times").respond(
        200, json=times("2026-10-13T10:00:00Z")
    )
    result = (
        await provider()
        .service_for(ctx(http))
        .book("2026-10-13T09:00:00+01:00", "Mary", "mary@example.ie")
    )
    assert result.booked is False
    assert result.say.startswith("That one has just gone.")
    assert [s.id for s in result.slots or []] == ["2026-10-13T11:00:00+01:00"]


async def test_bad_email_is_asked_again(
    http: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    result = (
        await provider()
        .service_for(ctx(http))
        .book("2026-10-13T09:00:00+01:00", "Mary", "mary at example")
    )
    assert result.booked is False and result.needs_email is True
    assert not calendly.calls
    calendly.get(f"/event_types/{EVENT_TYPE_UUID}").respond(
        200, json={"resource": event_type(locations=[], custom_questions=[])}
    )
    calendly.post("/invitees").respond(
        400,
        json={
            "title": "Invalid Argument",
            "message": "The supplied parameters are invalid.",
            "details": [{"parameter": "invitee.email", "message": "is invalid"}],
        },
    )
    again = (
        await provider()
        .service_for(ctx(http))
        .book("2026-10-13T09:00:00+01:00", "Mary", "mary@example.iee")
    )
    assert again.needs_email is True


async def test_no_answer_after_posting_is_unconfirmed_and_not_retried(
    http: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    calendly.get(f"/event_types/{EVENT_TYPE_UUID}").respond(
        200, json={"resource": event_type(locations=[], custom_questions=[])}
    )
    post = calendly.post("/invitees").mock(side_effect=httpx.ReadTimeout("slow"))
    result = (
        await provider()
        .service_for(ctx(http))
        .book("2026-10-13T09:00:00+01:00", "Mary", "mary@example.ie")
    )
    assert result.booked is False and result.handoff == "unconfirmed"
    assert post.call_count == 1


async def test_required_question_it_cannot_answer_is_handed_off(
    http: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    question = {
        "name": "Which clinic?",
        "type": "single_select",
        "position": 0,
        "enabled": True,
        "required": True,
        "answer_choices": ["Cork", "Galway"],
        "include_other": False,
    }
    calendly.get(f"/event_types/{EVENT_TYPE_UUID}").respond(
        200, json={"resource": event_type(locations=[], custom_questions=[question])}
    )
    post = calendly.post("/invitees")
    result = (
        await provider()
        .service_for(ctx(http))
        .book("2026-10-13T09:00:00+01:00", "Mary", "mary@example.ie")
    )
    assert result.handoff == "cannot_book"
    assert not post.called


async def test_oauth_token_is_refreshed_once_when_refused(
    http: httpx.AsyncClient,
) -> None:
    oauth = FakeOAuth(tokens=["old-token", "new-token"])
    with respx.mock(base_url=API) as router:
        route = router.get("/event_type_available_times").mock(
            side_effect=[
                httpx.Response(401, json={"title": "Unauthenticated"}),
                httpx.Response(200, json=times("2026-10-13T08:00:00Z")),
            ]
        )
        result = (
            await provider()
            .service_for(ctx(http, oauth=oauth))
            .availability("tomorrow", None)
        )
    assert len(result.slots) == 1
    assert route.calls[1].request.headers["Authorization"] == "Bearer new-token"
    assert oauth.rejected_seen == [None, "old-token"]


# -- picking the event type, testing, listing -----------------------------------


async def test_choices_list_active_event_types_with_warnings(
    http: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    other = f"{API}/event_types/ET-2222"
    route = calendly.get("/event_types").respond(
        200,
        json={
            "collection": [
                event_type(),
                event_type(
                    uri=other,
                    name="Site visit",
                    duration=60,
                    locations=[{"kind": "ask_invitee"}],
                    custom_questions=[],
                ),
            ],
            "pagination": {"next_page_token": None},
        },
    )
    found = await provider().config_choices(ctx(http, cfg={}))
    assert found.field == "event_type"
    assert [(c.label, c.detail) for c in found.choices] == [
        ("Consultation", "30 minutes"),
        ("Site visit", "1 hour"),
    ]
    assert found.choices[0].warning is None
    assert found.choices[1].warning is not None
    assert found.choices[1].config == {
        "event_type": other,
        "event_type_name": "Site visit",
    }
    assert query(route.calls[0].request) == {
        "user": USER,
        "active": "true",
        "count": "100",
    }


async def test_connection_test_names_the_event(
    http: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    calendly.get(f"/event_types/{EVENT_TYPE_UUID}").respond(
        200, json={"resource": event_type()}
    )
    result = await provider().test_connection(ctx(http))
    assert result.ok is True
    assert result.message == "Calendly is connected. Callers book 'Consultation'."
    assert result.account_label == "aoife@example.ie"
    unset = await provider().test_connection(ctx(http, cfg={}))
    assert unset.ok is True and "Choose which Calendly event" in unset.message


async def test_list_bookings_keeps_only_this_connections(
    http: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    def event(
        uuid_: str, status: str = "active", kind: str = EVENT_TYPE
    ) -> dict[str, Any]:
        return {
            "uri": f"{API}/scheduled_events/{uuid_}",
            "status": status,
            "start_time": "2026-10-13T08:00:00.000000Z",
            "end_time": "2026-10-13T08:30:00.000000Z",
            "event_type": kind,
            "location": {"type": "outbound_call", "location": "+353871234567"},
        }

    calendly.get("/scheduled_events").respond(
        200,
        json={
            "collection": [
                event("EV-1"),
                event("EV-2", status="canceled"),
                event("EV-3"),
                event("EV-4", kind=f"{API}/event_types/OTHER"),
            ],
            "pagination": {"next_page_token": None},
        },
    )

    def invitee(source: str, content: str) -> dict[str, Any]:
        return {
            "collection": [
                {
                    "name": "Mary Byrne",
                    "status": "active",
                    "created_at": "2026-10-12T06:00:00.000000Z",
                    "tracking": {"utm_source": source, "utm_content": content},
                    "questions_and_answers": [
                        {
                            "question": "Please share anything",
                            "answer": "Knee",
                            "position": 1,
                        }
                    ],
                }
            ]
        }

    ours = invitee("lightmove-ai", str(CONNECTION_ID))
    calendly.get("/scheduled_events/EV-1/invitees").respond(200, json=ours)
    calendly.get("/scheduled_events/EV-2/invitees").respond(200, json=ours)
    calendly.get("/scheduled_events/EV-3/invitees").respond(
        200, json=invitee("newsletter", "")
    )
    found = await provider().list_bookings(ctx(http), NOW, NOW + timedelta(days=7))
    assert [(b.event_id, b.status) for b in found] == [
        ("EV-1", "confirmed"),
        ("EV-2", "cancelled"),
    ]
    assert found[0].caller_name == "Mary Byrne"
    assert found[0].caller_phone == "+353871234567"
    assert found[0].reason == "Knee"


async def test_unreadable_bookings_give_an_admin_safe_error(
    http: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    calendly.get("/scheduled_events").respond(500, text="stack trace with secrets")
    with pytest.raises(BookingListFailed) as caught:
        await provider().list_bookings(ctx(http), NOW, NOW + timedelta(days=1))
    assert "stack trace" not in str(caught.value)
