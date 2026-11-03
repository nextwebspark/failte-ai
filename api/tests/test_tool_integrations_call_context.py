"""The caller's number the API passes to the tools service's MCP endpoints."""

from __future__ import annotations

import pytest

from api import constants
from api.services.tool_integrations.call_context import (
    CONTACT_PHONE_HEADER,
    contact_phone,
    tools_service_headers,
)

TOOLS_URL = "http://fallcha-tools:8000"
INBOUND = {
    "provider": "twilio",
    "direction": "inbound",
    "caller_number": "+353 87 123 4567",
    "called_number": "+35315550000",
}


@pytest.fixture(autouse=True)
def tools_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(constants, "TOOLS_SERVICE_URL", TOOLS_URL)


def test_the_other_party_of_a_telephony_call() -> None:
    assert contact_phone(INBOUND) == "+353 87 123 4567"
    outbound = {**INBOUND, "direction": "outbound"}
    assert contact_phone(outbound) == "+35315550000"
    assert contact_phone({**INBOUND, "provider": "ari"}) == "+353 87 123 4567"


@pytest.mark.parametrize(
    "context",
    [
        # Web and chat runs take context variables from the visitor's page.
        {**INBOUND, "provider": "smallwebrtc"},
        {**INBOUND, "provider": "webrtc"},
        {key: value for key, value in INBOUND.items() if key != "provider"},
        {**INBOUND, "direction": None},
        {**INBOUND, "direction": "sideways"},
        {**INBOUND, "caller_number": None},
        {**INBOUND, "caller_number": 353871234567},
        {**INBOUND, "caller_number": "unknown"},
        {**INBOUND, "caller_number": "anonymous"},
        {**INBOUND, "caller_number": "sip:+353871234567@pbx.example"},
        {**INBOUND, "caller_number": "+353871234567\r\nX-Evil: 1"},
        {**INBOUND, "caller_number": "12"},
    ],
)
def test_no_number_unless_the_call_record_has_a_usable_one(
    context: dict[str, object],
) -> None:
    assert contact_phone(context) is None


@pytest.mark.parametrize(
    "url",
    [
        f"{TOOLS_URL}/mcp/google-calendar",
        f"{TOOLS_URL}/mcp",
        f"{TOOLS_URL}/mcp/",
    ],
)
def test_headers_go_to_the_tools_service_mcp(url: str) -> None:
    assert tools_service_headers(url, INBOUND) == {
        CONTACT_PHONE_HEADER: "+353 87 123 4567"
    }


@pytest.mark.parametrize(
    "url",
    [
        "https://mcp.acme.example/mcp",
        "http://fallcha-tools:8000.acme.example/mcp/google-calendar",
        "https://fallcha-tools:8000/mcp/google-calendar",
        "http://fallcha-tools:8001/mcp/google-calendar",
        f"{TOOLS_URL}/v1/google-calendar/book",
        f"{TOOLS_URL}/mcpx",
        f"{TOOLS_URL}/mcp/google-calendar?forward=https://acme.example",
    ],
)
def test_no_headers_for_other_servers(url: str) -> None:
    assert tools_service_headers(url, INBOUND) == {}


def test_a_tools_service_behind_a_path_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(constants, "TOOLS_SERVICE_URL", "https://app.example/tools/")
    good = "https://app.example/tools/mcp/google-calendar"
    assert tools_service_headers(good, INBOUND) == {
        CONTACT_PHONE_HEADER: "+353 87 123 4567"
    }
    assert (
        tools_service_headers("https://app.example/mcp/google-calendar", INBOUND) == {}
    )


def test_no_headers_without_a_number_or_a_tools_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"{TOOLS_URL}/mcp/google-calendar"
    assert tools_service_headers(url, {**INBOUND, "provider": "smallwebrtc"}) == {}
    monkeypatch.setattr(constants, "TOOLS_SERVICE_URL", None)
    assert tools_service_headers(url, INBOUND) == {}
