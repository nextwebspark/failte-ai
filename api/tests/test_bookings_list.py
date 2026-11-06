"""IntegrationService.list_bookings: merges every connected calendar's
bookings, and one unreadable calendar does not hide the others. The tools
service is faked in memory; no database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from api.errors.integrations import (
    IntegrationConflictError,
    ToolsServiceUnavailableError,
)
from api.schemas.integrations import (
    IntegrationBooking,
    IntegrationCatalogResponse,
    IntegrationConnection,
)
from api.services.tool_integrations.service import (
    CALENDAR_UNREADABLE,
    Actor,
    IntegrationService,
)

START = datetime(2026, 10, 12, tzinfo=UTC)
END = START + timedelta(days=14)
CALENDAR = "google-calendar"


def _catalog() -> IntegrationCatalogResponse:
    def provider(pid: str, title: str, capabilities: list[str]) -> dict[str, Any]:
        return {
            "id": pid,
            "title": title,
            "description": "",
            "icon": "calendar",
            "auth_modes": ["service_account"],
            "scopes": [],
            "tools": [],
            "capabilities": capabilities,
        }

    return IntegrationCatalogResponse.model_validate(
        {
            "providers": [
                provider(CALENDAR, "Google Calendar", ["bookings"]),
                provider("google-sheets", "Google Sheets", []),
            ]
        }
    )


def _connection(provider: str = CALENDAR, **overrides: Any) -> IntegrationConnection:
    now = datetime.now(UTC)
    return IntegrationConnection.model_validate(
        {
            "id": str(uuid.uuid4()),
            "provider": provider,
            "auth_mode": "service_account",
            "account_label": "bot@demo.iam.gserviceaccount.com",
            "config": {"calendar_id": "c@group.calendar.google.com"},
            "status": "active",
            "created_at": now,
            "updated_at": now,
            **overrides,
        }
    )


def _booking(hour: int, name: str, **overrides: Any) -> IntegrationBooking:
    start = START + timedelta(days=3, hours=hour)
    return IntegrationBooking.model_validate(
        {
            "event_id": f"evt-{name}",
            "start": start,
            "end": start + timedelta(minutes=90),
            "status": "confirmed",
            "caller_name": name,
            "party_size": 2,
            **overrides,
        }
    )


class FakeTools:
    def __init__(
        self,
        connections: list[IntegrationConnection],
        bookings: dict[uuid.UUID, list[IntegrationBooking] | Exception],
    ) -> None:
        self.connections = connections
        self.bookings = bookings
        self.asked: list[uuid.UUID] = []

    async def get_catalog(self, caller: Any) -> IntegrationCatalogResponse:
        return _catalog()

    async def list_connections(self, caller: Any) -> list[IntegrationConnection]:
        return self.connections

    async def list_bookings(
        self, caller: Any, connection_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[IntegrationBooking]:
        assert (start, end) == (START, END)
        self.asked.append(connection_id)
        result = self.bookings[connection_id]
        if isinstance(result, Exception):
            raise result
        return result


def _service(tools: FakeTools) -> IntegrationService:
    return IntegrationService(
        tools_service=tools,  # type: ignore[arg-type]
        resources=SimpleNamespace(),  # type: ignore[arg-type]
        tools_base_url="http://tools.test",
    )


ACTOR = Actor(organization_id=7, user=SimpleNamespace(id=3))  # type: ignore[arg-type]


async def test_bookings_from_every_calendar_in_start_order() -> None:
    dinner = _connection()
    lunch = _connection(config={"calendar_id": "x", "ai_booking_enabled": False})
    sheets = _connection("google-sheets")
    revoked = _connection(status="revoked")
    tools = FakeTools(
        [dinner, lunch, sheets, revoked],
        {
            dinner.id: [_booking(19, "Byrne"), _booking(17, "Murphy")],
            lunch.id: [_booking(12, "Kelly", status="cancelled")],
        },
    )

    result = await _service(tools).list_bookings(ACTOR, START, END)

    assert [b.caller_name for b in result.bookings] == ["Kelly", "Murphy", "Byrne"]
    assert result.bookings[0].connection_id == lunch.id
    assert result.bookings[0].status == "cancelled"
    assert [
        (c.connection_id, c.ai_booking_enabled, c.ok) for c in result.calendars
    ] == [
        (dinner.id, True, True),
        (lunch.id, False, True),
    ]
    assert set(tools.asked) == {dinner.id, lunch.id}  # not Sheets, not revoked


async def test_an_unreadable_calendar_is_reported_not_fatal() -> None:
    good = _connection()
    unshared = _connection(status="error")
    down = _connection()
    tools = FakeTools(
        [good, unshared, down],
        {
            good.id: [_booking(19, "Byrne")],
            unshared.id: IntegrationConflictError(
                "the calendar was not found; make sure it is shared with bot@x"
            ),
            down.id: ToolsServiceUnavailableError(),
        },
    )

    result = await _service(tools).list_bookings(ACTOR, START, END)

    assert [b.caller_name for b in result.bookings] == ["Byrne"]
    by_id = {c.connection_id: c for c in result.calendars}
    assert by_id[good.id].ok and by_id[good.id].error is None
    assert by_id[unshared.id].ok is False
    assert "shared with bot@x" in (by_id[unshared.id].error or "")
    assert by_id[down.id].error == CALENDAR_UNREADABLE


async def test_no_calendars_means_an_empty_answer() -> None:
    result = await _service(FakeTools([], {})).list_bookings(ACTOR, START, END)
    assert result.calendars == [] and result.bookings == []


async def test_unexpected_errors_are_not_swallowed() -> None:
    broken = _connection()
    tools = FakeTools([broken], {broken.id: RuntimeError("bug")})
    with pytest.raises(RuntimeError):
        await _service(tools).list_bookings(ACTOR, START, END)


class SwitchTools(FakeTools):
    def __init__(self, connection: IntegrationConnection) -> None:
        super().__init__([connection], {})
        self.connection = connection
        self.patched: list[dict[str, Any]] = []

    async def get_connection(
        self, caller: Any, connection_id: uuid.UUID
    ) -> IntegrationConnection:
        assert connection_id == self.connection.id
        return self.connection

    async def update_config(
        self, caller: Any, connection_id: uuid.UUID, config: dict[str, Any]
    ) -> IntegrationConnection:
        self.patched.append(dict(config))
        return self.connection.model_copy(
            update={"config": {**self.connection.config, **config}}
        )


async def test_switching_ai_booking_changes_only_that_setting() -> None:
    calendar = _connection(config={"calendar_id": "c", "max_bookings_at_once": 5})
    tools = SwitchTools(calendar)

    result = await _service(tools).set_ai_booking(
        ACTOR, calendar.id, {"ai_booking_enabled": False}
    )

    assert tools.patched == [{"ai_booking_enabled": False}]
    assert result.ai_booking_enabled is False
    assert result.title == "Google Calendar"


async def test_the_switch_refuses_connections_that_are_not_calendars() -> None:
    from api.errors.integrations import IntegrationNotFoundError

    sheet = _connection("google-sheets")
    tools = SwitchTools(sheet)
    with pytest.raises(IntegrationNotFoundError):
        await _service(tools).set_ai_booking(
            ACTOR, sheet.id, {"ai_booking_enabled": False}
        )
    assert tools.patched == []


async def test_owner_switches_cannot_change_other_calendar_settings() -> None:
    calendar = _connection()
    tools = SwitchTools(calendar)

    result = await _service(tools).set_ai_booking(
        ACTOR,
        calendar.id,
        {"ai_changes_enabled": True, "max_bookings_at_once": 500},
    )

    assert tools.patched == [{"ai_changes_enabled": True}]
    assert result.ai_changes_enabled is True
    assert result.ai_booking_enabled is True


def test_the_request_needs_at_least_one_switch() -> None:
    from pydantic import ValidationError

    from api.schemas.integrations import AiBookingRequest

    with pytest.raises(ValidationError):
        AiBookingRequest.model_validate({})
    with pytest.raises(ValidationError):
        AiBookingRequest.model_validate({"max_bookings_at_once": 5})
    assert AiBookingRequest(ai_changes_enabled=False).changes() == {
        "ai_changes_enabled": False
    }
