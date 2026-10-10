"""Google Calendar through the app: connections, MCP and REST compatibility."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastmcp.exceptions import ToolError
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from fallcha_tools.config import Settings
from fallcha_tools.core.provider import ProviderRegistry
from fallcha_tools.providers import build_registry
from fallcha_tools.providers.google_calendar import (
    GoogleCalendarProvider,
    booking_id_key_from,
)
from fallcha_tools.providers.google_calendar.credentials import TokenCache
from tests.conftest import create_echo_connection, internal_headers, issue_key
from tests.echo_provider import EchoProvider
from tests.google_fakes import (
    BOOKING_KEY,
    CALENDAR_ID,
    PRIVATE_KEY_PEM,
    SA_EMAIL,
    FakeClock,
    FakeGoogle,
    calendar_config,
    google_error,
    json_body,
    service_account_key,
)
from tests.test_mcp import initialize, mcp_client

PROVIDER = "google-calendar"
TOOLS = {
    "check_appointment_availability",
    "book_appointment",
    "cancel_appointment",
    "look_up_order",
}


@pytest.fixture
def registry() -> ProviderRegistry:
    clock = FakeClock()
    return ProviderRegistry(
        [
            GoogleCalendarProvider(
                booking_id_key=BOOKING_KEY,
                token_cache=TokenCache(clock=clock),
                clock=clock,
            ),
            EchoProvider(),
        ]
    )


@pytest.fixture
def google() -> Iterator[FakeGoogle]:
    with respx.mock(assert_all_called=False) as router:
        yield FakeGoogle(router)


async def create_connection(
    client: httpx.AsyncClient,
    *,
    org_id: int = 1,
    config: dict[str, JsonValue] | None = None,
    secret: dict[str, JsonValue] | None = None,
) -> httpx.Response:
    return await client.post(
        "/internal/connections",
        headers=internal_headers(org_id),
        json={
            "provider": PROVIDER,
            "auth_mode": "service_account",
            "secret": secret if secret is not None else service_account_key(),
            "config": config if config is not None else calendar_config(),
        },
    )


async def connected_key(
    client: httpx.AsyncClient, *, org_id: int = 1, **config: JsonValue
) -> str:
    response = await create_connection(
        client, org_id=org_id, config=calendar_config(**config)
    )
    assert response.status_code == 201, response.text
    return await issue_key(client, response.json()["id"], org_id=org_id)


def test_build_registry_serves_google_calendar(settings: Settings) -> None:
    registry = build_registry(settings)
    assert [p.id for p in registry] == [PROVIDER]
    provider = registry.get(PROVIDER)
    assert isinstance(provider, GoogleCalendarProvider)
    secret = settings.internal_secret.get_secret_value()
    # Same secret on every replica -> same booking ids; never the raw secret.
    assert provider.booking_id_key == booking_id_key_from(secret)
    assert provider.booking_id_key != secret.encode()
    assert BOOKING_KEY not in repr(provider).encode()


# --- connections ----------------------------------------------------------


async def test_catalog_lists_tools_and_config_schema(client: httpx.AsyncClient) -> None:
    response = await client.get("/internal/catalog", headers=internal_headers())
    providers = {p["id"]: p for p in response.json()["providers"]}
    calendar = providers[PROVIDER]
    assert calendar["auth_modes"] == ["oauth2", "service_account"]
    assert calendar["oauth"] == {
        "scopes": [
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/calendar.readonly",
        ],
        "optional_scopes": ["https://www.googleapis.com/auth/spreadsheets.readonly"],
        "redirect_uri": None,
    }
    assert providers["echo"]["oauth"] is None
    assert {t["name"] for t in calendar["tools"]} == TOOLS
    schema = calendar["config_schema"]
    assert schema["required"] == ["calendar_id"]
    assert "timezone" in schema["properties"]
    assert providers["echo"]["config_schema"] is None


async def test_config_is_validated_stored_and_returned(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    created = await create_connection(client)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["config"]["calendar_id"] == CALENDAR_ID
    assert body["config"]["slot_minutes"] == 30  # defaults are materialised
    async with engine.connect() as conn:
        stored = (
            await conn.execute(
                text("SELECT config, secret_enc FROM fallcha_tools.connections")
            )
        ).one()
    assert stored.config["event_summary_prefix"] == "Acme call"
    assert SA_EMAIL not in stored.secret_enc


@pytest.mark.parametrize(
    ("config", "fragment"),
    [
        ({}, "calendar_id: Field required"),
        ({"calendar_id": "c", "timezone": "Nowhere/City"}, "unknown time zone"),
        ({"calendar_id": "c", "surprise": True}, "surprise"),
        ({"calendar_id": "c", "open_hour": 18}, "open_hour must be before close_hour"),
    ],
)
async def test_invalid_config_rejected(
    client: httpx.AsyncClient, config: dict[str, JsonValue], fragment: str
) -> None:
    response = await create_connection(client, config=config)
    assert response.status_code == 422
    assert fragment in response.json()["detail"]


async def test_invalid_service_account_rejected_without_echo(
    client: httpx.AsyncClient,
) -> None:
    broken_pem = PRIVATE_KEY_PEM[:200]
    response = await create_connection(
        client, secret=service_account_key(private_key=broken_pem)
    )
    assert response.status_code == 422
    assert "private_key" in response.json()["detail"]
    assert broken_pem[40:120] not in response.text

    wrong_type = await create_connection(client, secret={"type": "authorized_user"})
    assert wrong_type.status_code == 422


async def test_provider_without_config_model_rejects_config(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/internal/connections",
        headers=internal_headers(),
        json={
            "provider": "echo",
            "auth_mode": "api_key",
            "secret": {"api_key": "k"},
            "config": {"x": 1},
        },
    )
    assert response.status_code == 422
    assert "takes no config" in response.json()["detail"]


async def test_patch_config(client: httpx.AsyncClient) -> None:
    connection_id = (await create_connection(client)).json()["id"]
    url = f"/internal/connections/{connection_id}"

    updated = await client.patch(
        url,
        headers=internal_headers(),
        json={"config": calendar_config(timezone="Europe/London", slot_minutes=60)},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["config"]["timezone"] == "Europe/London"
    assert updated.json()["config"]["slot_minutes"] == 60

    # Partial patches merge: untouched fields keep their stored values.
    partial = await client.patch(
        url, headers=internal_headers(), json={"config": {"buffer_minutes": 0}}
    )
    assert partial.status_code == 200, partial.text
    merged = partial.json()["config"]
    assert merged["buffer_minutes"] == 0
    assert merged["timezone"] == "Europe/London"
    assert merged["slot_minutes"] == 60
    assert merged["calendar_id"] == CALENDAR_ID

    invalid = await client.patch(
        url, headers=internal_headers(), json={"config": {"timezone": "Nowhere/X"}}
    )
    assert invalid.status_code == 422
    unknown = await client.patch(
        url, headers=internal_headers(), json={"config": {"surprise": 1}}
    )
    assert unknown.status_code == 422
    other_org = await client.patch(
        url, headers=internal_headers(org_id=2), json={"config": calendar_config()}
    )
    assert other_org.status_code == 404

    await client.delete(url, headers=internal_headers())
    revoked = await client.patch(
        url, headers=internal_headers(), json={"config": calendar_config()}
    )
    assert revoked.status_code == 409


async def test_connection_test_checks_calendar_and_sheet(
    client: httpx.AsyncClient, google: FakeGoogle
) -> None:
    connection_id = (
        await create_connection(
            client, config=calendar_config(orders_sheet_id="sheet-123")
        )
    ).json()["id"]
    url = f"/internal/connections/{connection_id}/test"

    ok = (await client.post(url, headers=internal_headers())).json()
    assert ok["ok"] is True
    assert ok["message"] == (
        "Calendar 'Bookings' is reachable; orders sheet 'Orders' is readable"
    )
    assert ok["connection"]["account_label"] == SA_EMAIL

    google.calendar.mock(return_value=google_error(404, "notFound"))
    failed = (await client.post(url, headers=internal_headers())).json()
    assert failed["ok"] is False
    assert failed["connection"]["status"] == "error"
    assert f"shared with {SA_EMAIL}" in failed["message"]


# --- MCP ------------------------------------------------------------------


async def test_mcp_lists_and_calls_tools(
    app: FastAPI, client: httpx.AsyncClient, google: FakeGoogle
) -> None:
    key = await connected_key(client)

    async with mcp_client(app, f"http://tools/mcp/{PROVIDER}", key) as mcp:
        tools = {tool.name: tool for tool in await mcp.list_tools()}
        assert set(tools) == TOOLS
        book_schema = tools["book_appointment"].input_schema
        assert book_schema["required"] == ["slot_id", "caller_name", "caller_phone"]
        assert "never reformat" in book_schema["properties"]["slot_id"]["description"]

        available = await mcp.call_tool("check_appointment_availability", {})
        first = available.structured_content["slots"][0]
        assert first == {
            "id": "2026-10-12T09:00:00+01:00",
            "say": "Monday the twelfth at nine in the morning",
        }

        booked = await mcp.call_tool(
            "book_appointment",
            {"slot_id": first["id"], "caller_name": "Ann", "caller_phone": "087"},
        )
        assert booked.structured_content["booked"] is True
        assert (
            json_body(google.insert.calls.last.request)["summary"] == "Acme call — Ann"
        )

        cancelled = await mcp.call_tool(
            "cancel_appointment", {"event_id": booked.structured_content["event_id"]}
        )
        assert cancelled.structured_content["cancelled"] is True

        with pytest.raises(ToolError, match="ISO timestamp"):
            await mcp.call_tool(
                "book_appointment",
                {"slot_id": "soon", "caller_name": "Ann", "caller_phone": "087"},
            )
        with pytest.raises(ToolError, match="order lookup is not set up"):
            await mcp.call_tool(
                "look_up_order", {"caller_name": "Ann", "address_or_eircode": "X"}
            )
        google.free_busy.mock(
            return_value=google_error(403, "forbidden"), side_effect=None
        )
        with pytest.raises(ToolError, match="not accessible") as caught:
            await mcp.call_tool("check_appointment_availability", {})
        assert SA_EMAIL not in str(caught.value)


async def test_mcp_rejects_foreign_keys(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    echo_key = await issue_key(client, await create_echo_connection(client))
    assert await initialize(client, f"/mcp/{PROVIDER}", echo_key) == 401

    key = await connected_key(client)
    assert await initialize(client, f"/mcp/{PROVIDER}", key) == 200
    # A key whose org no longer matches its connection's org is inert.
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE fallcha_tools.connection_keys SET org_id = 2"))
    assert await initialize(client, f"/mcp/{PROVIDER}", key) == 401


# --- REST compatibility ---------------------------------------------------


async def test_rest_compat_with_bearer_and_x_api_key(
    client: httpx.AsyncClient, google: FakeGoogle
) -> None:
    key = await connected_key(client, orders_sheet_id="sheet-123")

    bearer = await client.post(
        f"/v1/{PROVIDER}/availability",
        headers={"Authorization": f"Bearer {key}"},
        json={"relative_day": "tomorrow", "part_of_day": "morning"},
    )
    assert bearer.status_code == 200, bearer.text
    assert bearer.json()["slots"][0]["id"] == "2026-10-13T09:00:00+01:00"
    assert set(bearer.json()) == {"slots", "say"}

    shim_style = {"X-API-Key": key}
    booked = await client.post(
        f"/v1/{PROVIDER}/book",
        headers=shim_style,
        json={
            "slot_id": "2026-10-13T09:00:00+01:00",
            "caller_name": "Ann",
            "caller_phone": "087",
        },
    )
    assert booked.status_code == 200
    event_id = booked.json()["event_id"]
    assert booked.json() == {
        "booked": True,
        "event_id": event_id,
        "say": "That is booked in for Tuesday the thirteenth at nine in the morning.",
    }

    google.sheet_values = [
        ["customer_name", "eircode", "status"],
        ["Ann Lee", "A1", "OK"],
    ]
    lookup = await client.post(
        f"/v1/{PROVIDER}/order_lookup",
        headers=shim_style,
        json={"caller_name": "Bob", "address_or_eircode": "Z9"},
    )
    assert lookup.status_code == 200
    assert set(lookup.json()) == {"verified", "say"}

    cancel = await client.post(
        f"/v1/{PROVIDER}/cancel", headers=shim_style, json={"event_id": event_id}
    )
    assert cancel.json()["cancelled"] is True


async def test_rest_error_statuses(
    client: httpx.AsyncClient, google: FakeGoogle
) -> None:
    headers = {"Authorization": f"Bearer {await connected_key(client)}"}

    bad_slot = await client.post(
        f"/v1/{PROVIDER}/book",
        headers=headers,
        json={"slot_id": "later", "caller_name": "A", "caller_phone": "1"},
    )
    assert bad_slot.status_code == 400
    unconfigured = await client.post(
        f"/v1/{PROVIDER}/order_lookup",
        headers=headers,
        json={"caller_name": "A", "address_or_eircode": "B"},
    )
    assert unconfigured.status_code == 409
    google.free_busy.mock(
        return_value=google_error(500, "backendError"), side_effect=None
    )
    upstream = await client.post(
        f"/v1/{PROVIDER}/availability", headers=headers, json={}
    )
    assert upstream.status_code == 502
    assert (
        upstream.json()["detail"]
        == "Google is temporarily unavailable; please try again"
    )


async def test_rest_rejects_missing_wrong_and_foreign_keys(
    client: httpx.AsyncClient, engine: AsyncEngine, google: FakeGoogle
) -> None:
    url = f"/v1/{PROVIDER}/availability"
    echo_key = await issue_key(client, await create_echo_connection(client))
    key = await connected_key(client)

    attempts: list[dict[str, str]] = [
        {},
        {"X-API-Key": "old-shared-shim-key"},
        {"Authorization": "Bearer ftk_" + "x" * 43},
        {"Authorization": f"Basic {key}"},
        {"Authorization": f"Bearer {echo_key}"},
    ]
    for headers in attempts:
        response = await client.post(url, headers=headers, json={})
        assert response.status_code == 401, headers

    assert (
        await client.post(url, headers={"X-API-Key": key}, json={})
    ).status_code == 200
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE fallcha_tools.connection_keys SET org_id = 99"))
    assert (
        await client.post(url, headers={"X-API-Key": key}, json={})
    ).status_code == 401
    assert not google.insert.called


async def test_each_key_reaches_only_its_own_connection(
    client: httpx.AsyncClient, google: FakeGoogle
) -> None:
    org1_key = await connected_key(client, org_id=1)
    org2_key = await connected_key(client, org_id=2, calendar_id="org2@example.com")
    google.free_busy.mock(
        side_effect=lambda request: httpx.Response(
            200,
            json={"calendars": {json_body(request)["items"][0]["id"]: {"busy": []}}},
        )
    )

    calendars: list[Any] = []
    for key in (org1_key, org2_key):
        response = await client.post(
            f"/v1/{PROVIDER}/availability", headers={"X-API-Key": key}, json={}
        )
        assert response.status_code == 200
        calendars.append(
            json_body(google.free_busy.calls.last.request)["items"][0]["id"]
        )
    assert calendars == [CALENDAR_ID, "org2@example.com"]
    # Separate connections also mint separate tokens.
    assert google.token.call_count == 2


async def test_revoked_connection_key_is_rejected_by_rest(
    client: httpx.AsyncClient,
) -> None:
    created = (await create_connection(client)).json()
    key = await issue_key(client, created["id"])
    await client.delete(
        f"/internal/connections/{created['id']}", headers=internal_headers()
    )
    response = await client.post(
        f"/v1/{PROVIDER}/availability", headers={"X-API-Key": key}, json={}
    )
    assert response.status_code == 401
    assert uuid.UUID(created["id"])  # sanity: ids are uuids
