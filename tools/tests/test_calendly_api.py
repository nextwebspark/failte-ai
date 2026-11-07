"""Calendly through ``/internal/*``: the token check on save and the event
type choices. Needs the test database; Calendly is mocked with respx."""

from __future__ import annotations

from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from fallcha_tools.config import Settings
from fallcha_tools.core.provider import ProviderRegistry
from fallcha_tools.providers.calendly import CalendlyProvider
from tests.conftest import internal_headers

API = "https://api.calendly.com"
TOKEN = "calendly-personal-access-token-0123456789"
EVENT_TYPE = f"{API}/event_types/ET-1"


@pytest.fixture
def registry() -> ProviderRegistry:
    return ProviderRegistry([CalendlyProvider()])


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "public_base_url": "https://tools.example",
            "ui_return_url": "https://app.example/integrations",
        }
    )


@pytest.fixture
def calendly() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=API, assert_all_called=False) as router:
        yield router


def me(router: respx.MockRouter, status: int = 200) -> respx.Route:
    return router.get("/users/me").respond(
        status,
        json={
            "resource": {
                "uri": f"{API}/users/U-1",
                "name": "Aoife Byrne",
                "email": "aoife@example.ie",
                "timezone": "Europe/Dublin",
            }
        },
    )


async def connect(client: httpx.AsyncClient) -> httpx.Response:
    return await client.post(
        "/internal/connections",
        headers=internal_headers(),
        json={
            "provider": "calendly",
            "auth_mode": "api_key",
            "secret": {"token": TOKEN},
        },
    )


async def test_catalog_offers_token_and_oauth(client: httpx.AsyncClient) -> None:
    response = await client.get("/internal/catalog", headers=internal_headers())
    [calendly] = response.json()["providers"]
    assert calendly["id"] == "calendly"
    assert sorted(calendly["auth_modes"]) == ["api_key", "oauth2"]
    assert set(calendly["capabilities"]) == {"bookings", "choices"}
    assert {t["name"] for t in calendly["tools"]} == {
        "check_appointment_availability",
        "book_appointment",
    }
    schema = calendly["config_schema"]["properties"]
    assert schema["event_type"]["x-fallcha-choice"] == "value"
    assert schema["event_type_name"]["x-fallcha-choice"] == "label"


async def test_token_is_checked_before_saving(
    client: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    route = me(calendly)
    response = await connect(client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["account_label"] == "aoife@example.ie"
    assert body["config"]["event_type"] is None
    assert TOKEN not in response.text
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"


async def test_rejected_token_saves_nothing(
    client: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    me(calendly, status=401)
    response = await connect(client)
    assert response.status_code == 422
    assert "didn't accept this token" in response.json()["detail"]
    assert TOKEN not in response.text
    listed = await client.get("/internal/connections", headers=internal_headers())
    assert listed.json()["connections"] == []


async def test_choices_then_pick(
    client: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    me(calendly)
    connection_id = (await connect(client)).json()["id"]
    calendly.get("/event_types").respond(
        200,
        json={
            "collection": [
                {
                    "uri": EVENT_TYPE,
                    "name": "Consultation",
                    "duration": 30,
                    "kind": "solo",
                    "locations": [],
                    "custom_questions": [],
                }
            ],
            "pagination": {"next_page_token": None},
        },
    )
    response = await client.get(
        f"/internal/connections/{connection_id}/choices", headers=internal_headers()
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["field"] == "event_type"
    [choice] = body["choices"]
    assert choice["label"] == "Consultation"
    picked = await client.patch(
        f"/internal/connections/{connection_id}",
        headers=internal_headers(),
        json={"config": choice["config"]},
    )
    assert picked.status_code == 200, picked.text
    assert picked.json()["config"]["event_type"] == EVENT_TYPE
    assert picked.json()["config"]["event_type_name"] == "Consultation"


async def test_an_event_type_off_calendly_is_refused(
    client: httpx.AsyncClient, calendly: respx.MockRouter
) -> None:
    me(calendly)
    connection_id = (await connect(client)).json()["id"]
    response = await client.patch(
        f"/internal/connections/{connection_id}",
        headers=internal_headers(),
        json={"config": {"event_type": "https://evil.example/event_types/X"}},
    )
    assert response.status_code == 422


async def test_oauth_start_sends_the_browser_to_calendly(
    client: httpx.AsyncClient,
) -> None:
    created = await client.post(
        "/internal/provider-apps",
        headers=internal_headers(),
        json={
            "provider": "calendly",
            "client_id": "calendly-client-id",
            "client_secret": "calendly-client-secret",
        },
    )
    assert created.status_code == 201, created.text
    response = await client.post(
        "/internal/oauth/start",
        headers=internal_headers(user_id=42),
        json={"provider": "calendly", "provider_app_id": created.json()["id"]},
    )
    assert response.status_code == 200, response.text
    url = urlsplit(response.json()["authorization_url"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == (
        "https://auth.calendly.com/oauth/authorize"
    )
    params = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert params["client_id"] == "calendly-client-id"
    assert params["redirect_uri"] == "https://tools.example/oauth/calendly/callback"
    assert params["code_challenge_method"] == "S256"
    assert params["scope"].split() == [
        "users:read",
        "event_types:read",
        "availability:read",
        "scheduled_events:write",
    ]
    assert "calendly-client-secret" not in response.text
