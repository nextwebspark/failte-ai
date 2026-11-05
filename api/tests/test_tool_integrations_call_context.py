"""The caller's number the API passes to the tools service's MCP endpoints."""

from __future__ import annotations

import pytest

from api import constants
from api.enums import CallType
from api.services.tool_integrations.call_context import (
    CONTACT_PHONE_HEADER,
    telephony_contact_phone,
    tools_service_headers,
)

TOOLS_URL = "http://fallcha-tools:8000"
CALLER = "+353 87 123 4567"
BUSINESS = "+35315550000"
# A run row as the inbound telephony code creates it.
INBOUND = {
    "provider": "twilio",
    "direction": "inbound",
    "caller_number": CALLER,
    "called_number": BUSINESS,
}


@pytest.fixture(autouse=True)
def tools_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(constants, "TOOLS_SERVICE_URL", TOOLS_URL)


def test_the_other_party_by_the_runs_call_type() -> None:
    assert telephony_contact_phone(CallType.INBOUND, INBOUND) == CALLER
    assert telephony_contact_phone("inbound", INBOUND) == CALLER
    outbound = {"caller_number": BUSINESS, "called_number": CALLER}
    assert telephony_contact_phone(CallType.OUTBOUND, outbound) == CALLER
    assert telephony_contact_phone("outbound", outbound) == CALLER


def test_a_direction_in_the_context_never_overrides_the_call_type() -> None:
    # The public API lets the caller set "direction" in initial_context.
    forged = {**INBOUND, "direction": "outbound", "called_number": "+3538600000"}
    assert telephony_contact_phone(CallType.INBOUND, forged) == CALLER
    assert telephony_contact_phone(None, INBOUND) is None
    assert telephony_contact_phone("sideways", INBOUND) is None


@pytest.mark.parametrize(
    "number",
    [
        None,
        353871234567,
        "",
        "unknown",
        "anonymous",
        "Restricted",
        "sip:+353871234567@pbx.example",
        "+353871234567\r\nX-Evil: 1",
        "12",
        # Twilio's keypad digits for ANONYMOUS, RESTRICTED, BLOCKED, UNKNOWN.
        "+266696687",
        "+7378742833",
        "+2562533",
        "+8656696",
    ],
)
def test_hidden_withheld_or_unusable_numbers_are_none(number: object) -> None:
    run = {**INBOUND, "caller_number": number}
    assert telephony_contact_phone(CallType.INBOUND, run) is None


@pytest.mark.parametrize("own", [BUSINESS, "01 555 0000", "+353 1 555 0000"])
def test_the_businesss_own_number_is_treated_as_hidden(own: str) -> None:
    inbound = {**INBOUND, "caller_number": own}
    assert telephony_contact_phone(CallType.INBOUND, inbound) is None
    outbound = {"caller_number": BUSINESS, "called_number": own}
    assert telephony_contact_phone(CallType.OUTBOUND, outbound) is None


@pytest.mark.parametrize(
    "url",
    [
        f"{TOOLS_URL}/mcp/google-calendar",
        f"{TOOLS_URL}/mcp",
        f"{TOOLS_URL}/mcp/",
    ],
)
def test_headers_go_to_the_tools_service_mcp(url: str) -> None:
    assert tools_service_headers(url, CALLER) == {CONTACT_PHONE_HEADER: CALLER}


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
    assert tools_service_headers(url, CALLER) == {}


def test_a_tools_service_behind_a_path_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(constants, "TOOLS_SERVICE_URL", "https://app.example/tools/")
    good = "https://app.example/tools/mcp/google-calendar"
    assert tools_service_headers(good, CALLER) == {CONTACT_PHONE_HEADER: CALLER}
    assert (
        tools_service_headers("https://app.example/mcp/google-calendar", CALLER) == {}
    )


def test_no_headers_without_a_number_or_a_tools_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"{TOOLS_URL}/mcp/google-calendar"
    assert tools_service_headers(url, None) == {}
    monkeypatch.setattr(constants, "TOOLS_SERVICE_URL", None)
    assert tools_service_headers(url, CALLER) == {}
