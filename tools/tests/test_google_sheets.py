"""Google Sheets provider: cell helpers, service rules, and the app wiring."""

from __future__ import annotations

import base64
import dataclasses
import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from fallcha_tools.core.models import AuthMode
from fallcha_tools.core.provider import AccessToken, ConnectionContext, ProviderRegistry
from fallcha_tools.providers.google_common.credentials import TokenCache
from fallcha_tools.providers.google_common.errors import (
    BadArgumentError,
    GoogleApiError,
    NotConfiguredError,
)
from fallcha_tools.providers.google_common.scopes import (
    SHEETS_READONLY_SCOPE,
    SHEETS_SCOPE,
)
from fallcha_tools.providers.google_sheets import GoogleSheetsProvider
from fallcha_tools.providers.google_sheets.cells import (
    column_letter,
    header_names,
    neutralize_formula,
    updated_row_number,
)
from fallcha_tools.providers.google_sheets.orders import OrdersCache
from fallcha_tools.providers.google_sheets.provider import SHEETS_OAUTH
from fallcha_tools.providers.google_sheets.settings import SheetsConfig
from tests.conftest import internal_headers, issue_key
from tests.echo_provider import EchoProvider
from tests.google_fakes import SA_EMAIL, FakeClock, service_account_key
from tests.sheets_fakes import ORDERS, SPREADSHEET_ID, FakeSheets, sheets_config
from tests.test_mcp import mcp_client

PROVIDER = "google-sheets"


# --- pure helpers -------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "stored"),
    [
        ('=HYPERLINK("http://x")', '\'=HYPERLINK("http://x")'),
        ("+1+cmd|' /C calc'!A0", "'+1+cmd|' /C calc'!A0"),
        ("-2+3", "'-2+3"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\t=1", "'\t=1"),
        ("+353 87 123 4567", "+353 87 123 4567"),  # a phone number stays as is
        ("+1 (555) 010-9999", "+1 (555) 010-9999"),
        ("Mary", "Mary"),
        ("", ""),
    ],
)
def test_formula_values_are_neutralized(value: str, stored: str) -> None:
    assert neutralize_formula(value) == stored


def test_headers_columns_and_ranges() -> None:
    assert header_names(["Name", " ", "name", "Notes  x"]) == [
        "Name",
        "Column B",
        "name (2)",
        "Notes x",
    ]
    assert [column_letter(i) for i in (0, 25, 26, 701, 702)] == [
        "A",
        "Z",
        "AA",
        "ZZ",
        "AAA",
    ]
    assert updated_row_number("'Leads'!A12:D12") == 12
    assert updated_row_number("") is None


def test_config_accepts_a_url_and_checks_tabs() -> None:
    url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid=0"
    config = SheetsConfig.model_validate({"spreadsheet_id": url})
    assert config.spreadsheet_id == SPREADSHEET_ID
    assert config.max_rows_returned == 20 and config.header_row == 1
    deduped = SheetsConfig.model_validate(
        sheets_config(allowed_tabs=["Leads", " leads ", "Other"])
    )
    assert deduped.allowed_tabs == ["Leads", "Other"]
    with pytest.raises(ValidationError, match="default_tab must be one of"):
        SheetsConfig.model_validate(
            sheets_config(default_tab="Private", allowed_tabs=["Leads"])
        )
    with pytest.raises(ValidationError, match="spreadsheet id"):
        SheetsConfig.model_validate({"spreadsheet_id": "not an id!"})


# --- service against a fake Google --------------------------------------------


@pytest.fixture
def sheets() -> Iterator[FakeSheets]:
    with respx.mock(assert_all_called=False) as router:
        yield FakeSheets(router)


@dataclass
class FakeTokens:
    async def access_token(self, *, rejected: str | None = None) -> AccessToken:
        del rejected
        return AccessToken("oauth-token", datetime.now(UTC) + timedelta(hours=1))


def context(
    http: httpx.AsyncClient,
    *,
    auth_mode: AuthMode = AuthMode.SERVICE_ACCOUNT,
    scopes: tuple[str, ...] = (),
    **config: Any,
) -> ConnectionContext:
    oauth = auth_mode == AuthMode.OAUTH2
    return ConnectionContext(
        org_id=1,
        connection_id=uuid.uuid4(),
        provider=PROVIDER,
        auth_mode=auth_mode,
        secret={} if oauth else service_account_key(),
        access_token=None,
        http=http,
        config=sheets_config(**config),
        account_label="owner@acme.ie" if oauth else None,
        scopes_granted=scopes,
        oauth=FakeTokens() if oauth else None,
    )


def provider() -> GoogleSheetsProvider:
    clock = FakeClock()
    return GoogleSheetsProvider(token_cache=TokenCache(clock=clock), clock=clock)


async def test_find_rows_exact_and_contains(sheets: FakeSheets) -> None:
    async with httpx.AsyncClient() as http:
        svc = provider().service_for(context(http))
        exact = await svc.find_rows("phone", " +353 86 333  4444 ", None, "exact")
        assert exact.found and exact.count == 1 and not exact.more
        assert exact.tab == "Leads"  # first tab when no default is set
        assert exact.rows[0].row_number == 3
        assert exact.rows[0].values == {
            "Name": "John Walsh",
            "Phone": "+353 86 333 4444",
            "Status": "Won",
            "Notes": "",
        }
        contains = await svc.find_rows("Name", "MARY", "Leads", "contains")
        assert [r.row_number for r in contains.rows] == [2, 4]
        none = await svc.find_rows("Name", "Nobody", None, "exact")
        assert not none.found and none.rows == []
    # Ranges are quoted A1 and URL-encoded (never sent raw).
    assert sheets.batch_ranges[-1] == ["'Leads'!1:10001"]
    raw = sheets.batch.calls.last.request.url.raw_path.decode()
    assert "ranges=%27Leads%27%211%3A10001" in raw


async def test_find_rows_caps_results(sheets: FakeSheets) -> None:
    sheets.tabs["Leads"] += [["Same", str(i), "", ""] for i in range(30)]
    async with httpx.AsyncClient() as http:
        svc = provider().service_for(context(http, max_rows_returned=5))
        result = await svc.find_rows("Name", "same", None, "exact")
    assert result.count == 5 and result.more


async def test_unknown_column_lists_columns(sheets: FakeSheets) -> None:
    async with httpx.AsyncClient() as http:
        svc = provider().service_for(context(http))
        with pytest.raises(BadArgumentError, match="columns are: Name, Phone"):
            await svc.find_rows("Email", "x", None, "exact")


async def test_header_row_setting(sheets: FakeSheets) -> None:
    sheets.tabs["Leads"].insert(0, ["Lead list, exported 2026"])
    async with httpx.AsyncClient() as http:
        svc = provider().service_for(context(http, header_row=2))
        result = await svc.find_rows("Status", "won", None, "exact")
        assert result.rows[0].row_number == 4
        with pytest.raises(BadArgumentError, match="below the header row"):
            await svc.get_row(2, None)


async def test_allowed_tabs_are_enforced(sheets: FakeSheets) -> None:
    async with httpx.AsyncClient() as http:
        svc = provider().service_for(context(http, allowed_tabs=["Leads"]))
        with pytest.raises(BadArgumentError, match="use one of: Leads"):
            await svc.find_rows("Secret", "x", "Private", "exact")
        with pytest.raises(BadArgumentError, match="cannot be used"):
            await svc.get_row(2, "Private")
        with pytest.raises(BadArgumentError, match="cannot be used"):
            await svc.append_row({"Secret": "x"}, "Private")
        assert sheets.batch.call_count == 0 and sheets.append.call_count == 0
        # No tab given: the first allowed tab, without a metadata call.
        result = await svc.find_rows("Status", "new", None, "exact")
        assert result.found
    assert sheets.meta.call_count == 0
    assert sheets.batch_ranges == [["'Leads'!1:10001"]]


async def test_unknown_tab_and_quoted_tab_names(sheets: FakeSheets) -> None:
    async with httpx.AsyncClient() as http:
        svc = provider().service_for(context(http))
        with pytest.raises(BadArgumentError, match="tab was not found"):
            await svc.get_row(2, "Nope")
        got = await svc.get_row(2, "My 'Quoted' Tab")
    assert got.found and got.row is not None and got.row.values == {"Key": "v"}
    assert sheets.batch_ranges[-1][0] == "'My ''Quoted'' Tab'!1:1"


async def test_get_row(sheets: FakeSheets) -> None:
    async with httpx.AsyncClient() as http:
        svc = provider().service_for(context(http, default_tab="Leads"))
        got = await svc.get_row(2, None)
        assert got.row is not None and got.row.values["Name"] == "Mary Byrne"
        missing = await svc.get_row(99, None)
    assert not missing.found and missing.row is None
    assert sheets.meta.call_count == 0  # default tab: no metadata lookup


async def test_append_row_maps_headers_and_escapes(sheets: FakeSheets) -> None:
    async with httpx.AsyncClient() as http:
        svc = provider().service_for(context(http))
        result = await svc.append_row(
            {"phone": "+353 87 999 0000", "NAME": "=IMPORTXML(1)"}, None
        )
    assert result.appended and result.row_number == 5 and result.tab == "Leads"
    [call] = sheets.appended
    assert call["body"]["values"] == [["'=IMPORTXML(1)", "+353 87 999 0000"]]
    assert call["params"]["valueInputOption"] == "RAW"
    assert call["params"]["insertDataOption"] == "INSERT_ROWS"
    assert call["a1"] == "'Leads'!A1:D"


async def test_append_row_rejects_unknown_columns(sheets: FakeSheets) -> None:
    async with httpx.AsyncClient() as http:
        svc = provider().service_for(context(http))
        with pytest.raises(BadArgumentError, match=r"unknown column\(s\): Email"):
            await svc.append_row({"Name": "x", "Email": "a@b.c"}, None)
    assert sheets.append.call_count == 0


async def test_append_timeout_is_not_reported_as_lost(sheets: FakeSheets) -> None:
    sheets.append.side_effect = httpx.ReadTimeout("slow")
    async with httpx.AsyncClient() as http:
        svc = provider().service_for(context(http))
        with pytest.raises(GoogleApiError, match="check the sheet before") as info:
            await svc.append_row({"Name": "x"}, None)
    assert info.value.retryable


async def test_each_call_has_a_deadline(sheets: FakeSheets) -> None:
    seen: list[float] = []

    def slow(request: httpx.Request) -> httpx.Response:
        # What httpx does when the server outlives the request's read timeout.
        seen.append(request.extensions["timeout"]["read"])
        raise httpx.ReadTimeout("slow", request=request)

    sheets.batch.mock(side_effect=slow)
    async with httpx.AsyncClient() as http:
        svc = GoogleSheetsProvider(deadline_seconds=0.8).service_for(context(http))
        with pytest.raises(GoogleApiError, match="did not respond in time"):
            await svc.find_rows("Name", "x", "Leads", "exact")
    # The request got only what was left of the call's 0.8 s budget.
    assert seen and 0 < seen[0] <= 0.8


async def test_oauth_connection_uses_its_token(sheets: FakeSheets) -> None:
    async with httpx.AsyncClient() as http:
        svc = provider().service_for(
            context(http, auth_mode=AuthMode.OAUTH2, scopes=(SHEETS_SCOPE,))
        )
        await svc.find_rows("Name", "x", "Leads", "exact")
    request = sheets.batch.calls.last.request
    assert request.headers["Authorization"] == "Bearer oauth-token"
    assert sheets.token.call_count == 0


async def test_oauth_connection_without_write_scope(sheets: FakeSheets) -> None:
    async with httpx.AsyncClient() as http:
        svc = provider().service_for(
            context(http, auth_mode=AuthMode.OAUTH2, scopes=(SHEETS_READONLY_SCOPE,))
        )
        with pytest.raises(
            NotConfiguredError, match="did not allow access to Google Sheets"
        ):
            await svc.find_rows("Name", "x", "Leads", "exact")


async def test_missing_spreadsheet_setting() -> None:
    async with httpx.AsyncClient() as http:
        ctx = dataclasses.replace(context(http), config={})
        with pytest.raises(NotConfiguredError, match="not set up"):
            provider().service_for(ctx)


def test_oauth_spec() -> None:
    assert SHEETS_OAUTH.scopes == (SHEETS_SCOPE,)
    assert SHEETS_OAUTH.optional_scopes == ()
    assert SHEETS_OAUTH.authorize_params["access_type"] == "offline"


# --- through the app ----------------------------------------------------------


@pytest.fixture
def registry() -> ProviderRegistry:
    return ProviderRegistry([provider(), EchoProvider()])


async def create(
    client: httpx.AsyncClient, *, org_id: int = 1, **config: Any
) -> httpx.Response:
    return await client.post(
        "/internal/connections",
        headers=internal_headers(org_id),
        json={
            "provider": PROVIDER,
            "auth_mode": "service_account",
            "secret": service_account_key(),
            "config": sheets_config(**config),
        },
    )


async def test_catalog_entry(client: httpx.AsyncClient) -> None:
    response = await client.get("/internal/catalog", headers=internal_headers())
    entry = {p["id"]: p for p in response.json()["providers"]}[PROVIDER]
    assert entry["auth_modes"] == ["oauth2", "service_account"]
    assert entry["oauth"]["scopes"] == [SHEETS_SCOPE]
    assert {t["name"] for t in entry["tools"]} == {
        "find_rows",
        "get_row",
        "append_row",
        "look_up_order",
    }
    assert entry["config_schema"]["required"] == ["spreadsheet_id"]


async def test_connection_test_reads_metadata(
    client: httpx.AsyncClient, sheets: FakeSheets
) -> None:
    created = await create(client, allowed_tabs=["Leads"])
    assert created.status_code == 201, created.text
    # Labelled with the service account's email from the start.
    assert created.json()["account_label"] == SA_EMAIL
    connection_id = created.json()["id"]
    ok = await client.post(
        f"/internal/connections/{connection_id}/test", headers=internal_headers()
    )
    assert ok.json()["ok"], ok.text
    assert "'CRM'" in ok.json()["message"]
    assert ok.json()["connection"]["account_label"] == SA_EMAIL

    patched = await client.patch(
        f"/internal/connections/{connection_id}",
        headers=internal_headers(),
        json={"config": {"allowed_tabs": ["Leads", "Gone"]}},
    )
    assert patched.status_code == 200
    bad = await client.post(
        f"/internal/connections/{connection_id}/test", headers=internal_headers()
    )
    assert not bad.json()["ok"] and "'Gone'" in bad.json()["message"]

    sheets.meta.side_effect = None
    sheets.meta.return_value = httpx.Response(404, json={"error": {"code": 404}})
    unshared = await client.post(
        f"/internal/connections/{connection_id}/test", headers=internal_headers()
    )
    assert f"share it with {SA_EMAIL}" in unshared.json()["message"]


async def test_mcp_tools_end_to_end(
    app: FastAPI, client: httpx.AsyncClient, sheets: FakeSheets
) -> None:
    created = await create(client)
    key = await issue_key(client, created.json()["id"])
    async with mcp_client(app, "http://tools/mcp/google-sheets", key) as mcp:
        found = await mcp.call_tool("find_rows", {"column": "Status", "value": "won"})
        assert found.structured_content is not None
        assert found.structured_content["rows"][0]["values"]["Name"] == "John Walsh"
        added = await mcp.call_tool(
            "append_row", {"values": {"Name": "New Lead", "Status": "New"}}
        )
        assert added.structured_content is not None
        assert added.structured_content["appended"] is True
        with pytest.raises(ToolError, match="unknown column"):
            await mcp.call_tool("append_row", {"values": {"Bogus": "x"}})


async def test_keys_are_scoped_to_their_org_and_provider(
    app: FastAPI, client: httpx.AsyncClient, sheets: FakeSheets
) -> None:
    org_a = await create(client, org_id=1, default_tab="Leads")
    org_b = await create(client, org_id=2, default_tab="Private")
    key_b = await issue_key(client, org_b.json()["id"], org_id=2)
    # Org A cannot see or test org B's connection.
    other = await client.post(
        f"/internal/connections/{org_b.json()['id']}/test",
        headers=internal_headers(1),
    )
    assert other.status_code == 404
    assert org_a.status_code == 201
    async with mcp_client(app, "http://tools/mcp/google-sheets", key_b) as mcp:
        result = await mcp.call_tool("get_row", {"row_number": 2})
        assert result.structured_content is not None
        assert result.structured_content["tab"] == "Private"
    # The sheets key does not open the echo provider.
    with pytest.raises(Exception):  # noqa: B017 - 401 surfaces as a client error
        async with mcp_client(app, "http://tools/mcp/echo", key_b) as mcp:
            await mcp.list_tools()


# --- order lookup (moved here from Google Calendar) ----------------------------


def _token_scopes(sheets: FakeSheets) -> set[str]:
    scopes = set()
    for call in sheets.token.calls:
        assertion = parse_qs(call.request.content.decode())["assertion"][0]
        payload = assertion.split(".")[1]
        claims = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
        scopes.add(claims["scope"])
    return scopes


async def test_order_lookup_verifies_name_and_eircode(sheets: FakeSheets) -> None:
    async with httpx.AsyncClient() as http:
        svc = provider().service_for(context(http, orders_tab="Orders"))
        found = await svc.look_up_order("Murphy", "h91x2y3")
        assert found.verified is True and found.order_id == "VT-1"
        assert found.say == (
            "I have your order for the Home Fibre. "
            "The status is: Shipped. Arrives Thursday."
        )
        by_address = await svc.look_up_order("John Byrne", "rose cottage kinsale")
        assert by_address.verified is True and by_address.order_id == "VT-2"
        assert by_address.say.endswith("The status is: Pending.")
        wrong_address = await svc.look_up_order("Jane Murphy", "Dublin 4")
        unknown_name = await svc.look_up_order("Zed Nobody", "H91 X2Y3")
    assert wrong_address.verified is unknown_name.verified is False
    assert wrong_address.say == unknown_name.say
    assert wrong_address.model_dump(exclude_none=True).keys() == {"verified", "say"}
    # Cached for a minute (one read), with a read-only token.
    assert sheets.batch.call_count == 1
    assert sheets.batch_ranges == [["'Orders'!A1:Z1000"]]
    assert _token_scopes(sheets) == {SHEETS_READONLY_SCOPE}


async def test_order_lookup_cache_expires(sheets: FakeSheets) -> None:
    clock = FakeClock()
    p = GoogleSheetsProvider(token_cache=TokenCache(clock=clock), clock=clock)
    async with httpx.AsyncClient() as http:
        svc = p.service_for(context(http, orders_tab="Orders"))
        await svc.look_up_order("Murphy", "H91X2Y3")
        clock.advance(timedelta(seconds=61))
        await svc.look_up_order("Murphy", "H91X2Y3")
    assert sheets.batch.call_count == 2


async def test_order_lookup_uses_configured_columns(sheets: FakeSheets) -> None:
    sheets.tabs["Orders"][0] = [
        "Ref",
        "Customer",
        "Address",
        "Eircode",
        "Plan",
        "Status",
        "ETA",
    ]
    columns = {"order_id": "ref", "customer_name": "Customer", "package": "Plan"}
    async with httpx.AsyncClient() as http:
        svc = provider().service_for(
            context(http, orders_tab="Orders", order_columns=columns)
        )
        found = await svc.look_up_order("Murphy", "H91 X2Y3")
    assert found.verified and found.order_id == "VT-1"
    assert found.package == "Home Fibre"


async def test_order_lookup_needs_an_orders_tab(sheets: FakeSheets) -> None:
    async with httpx.AsyncClient() as http:
        svc = provider().service_for(context(http))
        with pytest.raises(NotConfiguredError, match="not set up"):
            await svc.look_up_order("Murphy", "H91X2Y3")
    assert sheets.batch.call_count == 0


async def test_empty_or_header_only_orders_tab(sheets: FakeSheets) -> None:
    sheets.tabs["Orders"] = []
    async with httpx.AsyncClient() as http:
        svc = provider().service_for(context(http, orders_tab="Orders"))
        with pytest.raises(GoogleApiError, match="empty"):
            await svc.look_up_order("Murphy", "H91X2Y3")
    sheets.tabs["Orders"] = [list(ORDERS[0])]
    async with httpx.AsyncClient() as http:
        svc = provider().service_for(context(http, orders_tab="Orders"))
        result = await svc.look_up_order("Murphy", "H91X2Y3")
    assert result.verified is False


def test_orders_tab_must_be_allowed() -> None:
    with pytest.raises(ValidationError, match="orders_tab must be one of"):
        SheetsConfig.model_validate(
            sheets_config(orders_tab="Orders", allowed_tabs=["Leads"])
        )


async def test_orders_cache_bounded_and_drops_stale() -> None:
    clock = FakeClock()
    cache = OrdersCache(max_entries=2)

    async def fetch() -> list[dict[str, str]]:
        return []

    for n in range(3):
        await cache.rows((uuid.uuid4(), f"s{n}", "Orders"), clock(), fetch)
    assert len(cache) == 2
    clock.advance(timedelta(minutes=5))
    await cache.rows((uuid.uuid4(), "fresh", "Orders"), clock(), fetch)
    assert len(cache) == 1


async def test_order_lookup_rest_compat_and_mcp(
    app: FastAPI, client: httpx.AsyncClient, sheets: FakeSheets
) -> None:
    created = await create(client, orders_tab="Orders")
    key = await issue_key(client, created.json()["id"])
    shim_style = {"X-API-Key": key}
    miss = await client.post(
        f"/v1/{PROVIDER}/order_lookup",
        headers=shim_style,
        json={"caller_name": "Bob", "address_or_eircode": "Z9"},
    )
    assert miss.status_code == 200
    assert set(miss.json()) == {"verified", "say"}
    hit = await client.post(
        f"/v1/{PROVIDER}/order_lookup",
        headers={"Authorization": f"Bearer {key}"},
        json={"caller_name": "Jane Murphy", "address_or_eircode": "H91 X2Y3"},
    )
    assert hit.json()["verified"] is True and hit.json()["order_id"] == "VT-1"
    async with mcp_client(app, "http://tools/mcp/google-sheets", key) as mcp:
        result = await mcp.call_tool(
            "look_up_order",
            {"caller_name": "Murphy", "address_or_eircode": "H91X2Y3"},
        )
        assert result.structured_content is not None
        assert result.structured_content["verified"] is True

    unconfigured = await create(client)
    other_key = await issue_key(client, unconfigured.json()["id"])
    conflict = await client.post(
        f"/v1/{PROVIDER}/order_lookup",
        headers={"Authorization": f"Bearer {other_key}"},
        json={"caller_name": "A", "address_or_eircode": "B"},
    )
    assert conflict.status_code == 409
