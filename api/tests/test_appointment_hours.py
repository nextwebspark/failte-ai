"""Appointment hours of a template agent: the structured answer, the sentence
it puts in the prompt, and saving it as the attached Google Calendar
connection's booking hours (through the integrations service and the tools
service client, whose HTTP is mocked here)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.errors.integrations import (
    IntegrationInvalidRequestError,
    ToolsServiceNotConfiguredError,
    ToolsServiceUnavailableError,
)
from api.routes.workflow import router
from api.schemas.appointment_hours import AppointmentHours, CalendarHoursStatus
from api.schemas.integrations import IntegrationConnectionResponse
from api.schemas.workflow_template import (
    DuplicateTemplateRequest,
    SetupFieldType,
    TemplateSetupField,
)
from api.services.auth import depends as auth_depends
from api.services.auth.depends import get_user
from api.services.auth.permissions import Permission
from api.services.tool_integrations import Actor, IntegrationService
from api.services.tool_integrations.client import ToolsServiceClient
from api.services.tool_integrations.resources import LinkedCredential
from api.services.workflow import appointment_hours as hours_module
from api.services.workflow.agent_builder import validate_workflow_definition
from api.services.workflow.appointment_hours import (
    appointment_hours_answers,
    calendar_config_patch,
    describe_appointment_hours,
    update_calendar_booking_hours,
)
from api.services.workflow.starter_templates import STARTER_TEMPLATES
from api.services.workflow.template_setup import (
    TemplateSetupError,
    attach_integration_tools,
    fill_template_values,
)

ORG_ID = 11
TOOL = "cal-tool-9"
CONNECTION_ID = uuid.UUID("0b6f1f0e-1c1a-4d3e-9a55-5f6c7e8d9a0b")
TOOLS_URL = "http://tools.test"
SECRET = "internal-secret-for-tests-0123456789"

FIELDS = [
    TemplateSetupField(key="business_name", label="Business name"),
    TemplateSetupField(
        key="appointment_hours",
        label="Appointment hours",
        type=SetupFieldType.APPOINTMENT_HOURS,
        required=False,
    ),
]
DEFAULT_HOURS = AppointmentHours()
WEEKEND_MORNINGS = {
    "booking_days": [6, 5, 5],
    "open_hour": 8,
    "close_hour": 12,
    "slot_minutes": 45,
    "timezone": "America/New_York",
}


# -- the structured answer ----------------------------------------------------


def test_defaults_match_the_calendar_connection_defaults():
    hours = AppointmentHours()

    assert hours.booking_days == (0, 1, 2, 3, 4)
    assert (hours.open_hour, hours.close_hour, hours.slot_minutes) == (9, 17, 30)
    assert hours.timezone == "Europe/Dublin"


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Calcutta"])
def test_accepts_iana_zones_including_legacy_names_browsers_report(zone):
    assert AppointmentHours(timezone=zone).timezone == zone


def test_days_are_sorted_and_deduplicated():
    assert AppointmentHours.model_validate(WEEKEND_MORNINGS).booking_days == (5, 6)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"timezone": "Mars/Olympus"}, "Unknown time zone"),
        ({"timezone": "../etc/passwd"}, "Unknown time zone"),
        # A file in the tz database that is not a zone.
        ({"timezone": "posixrules"}, "Unknown time zone"),
        ({"open_hour": 17, "close_hour": 9}, "closing hour must be after"),
        ({"open_hour": 9, "close_hour": 9}, "closing hour must be after"),
        ({"open_hour": 9, "close_hour": 10, "slot_minutes": 90}, "longer than"),
        ({"booking_days": []}, "at least 1"),
        ({"booking_days": [7]}, "booking_days"),
        ({"close_hour": 25}, "close_hour"),
        ({"slot_minutes": 241}, "slot_minutes"),
        ({"buffer_minutes": 10}, "Extra inputs"),
    ],
)
def test_rejects_hours_the_calendar_cannot_take(overrides, message):
    with pytest.raises(ValidationError, match=message):
        AppointmentHours.model_validate(overrides)


@pytest.mark.parametrize(
    ("hours", "when"),
    [
        ({}, "Monday to Friday, 9:00–17:00 (Europe/Dublin time), 30 minutes"),
        (
            WEEKEND_MORNINGS,
            "Saturday and Sunday, 8:00–12:00 (America/New_York time), 45 minutes",
        ),
        (
            {"booking_days": [0, 2, 4], "slot_minutes": 60},
            "Monday, Wednesday and Friday, 9:00–17:00 (Europe/Dublin time), 1 hour",
        ),
        (
            {"booking_days": [0, 1, 2, 4, 5], "open_hour": 18, "close_hour": 24},
            (
                "Monday to Wednesday, Friday and Saturday, 18:00–midnight "
                "(Europe/Dublin time), 30 minutes"
            ),
        ),
        (
            {"booking_days": list(range(7)), "open_hour": 0, "close_hour": 24},
            "every day, all day (Europe/Dublin time), 30 minutes",
        ),
        (
            {"booking_days": [3], "slot_minutes": 120},
            "Thursday, 9:00–17:00 (Europe/Dublin time), 2 hours",
        ),
        (
            {"booking_days": [6], "open_hour": 0, "close_hour": 6},
            "Sunday, 0:00–6:00 (Europe/Dublin time), 30 minutes",
        ),
    ],
)
def test_describes_the_hours_in_one_sentence(hours, when):
    sentence = describe_appointment_hours(AppointmentHours.model_validate(hours))

    assert sentence == f"Appointments can be booked {when} each."


def test_calendar_patch_holds_only_the_booking_hours():
    patch_ = calendar_config_patch(AppointmentHours.model_validate(WEEKEND_MORNINGS))

    # calendar_id, buffer, lead time, ... are left out, so the tools service
    # keeps them (its PATCH merges top-level keys).
    assert patch_ == {
        "booking_days": [5, 6],
        "open_hour": 8,
        "close_hour": 12,
        "slot_minutes": 45,
        "timezone": "America/New_York",
    }


# -- the request ---------------------------------------------------------------


def _request(**body: Any) -> DuplicateTemplateRequest:
    return DuplicateTemplateRequest.model_validate(
        {"template_id": 3, "workflow_name": "Reception", **body}
    )


def test_only_hours_can_be_applied_to_the_calendar():
    with pytest.raises(ValidationError, match="apply_to_calendar needs"):
        _request(apply_to_calendar=True, integration_tools={"google-calendar": TOOL})


# -- filling the template ------------------------------------------------------


def test_the_hours_field_is_answered_with_a_line():
    answers = appointment_hours_answers(
        FIELDS,
        _request(
            values={"business_name": "Bloom"},
            appointment_hours={},
            integration_tools={"google-calendar": TOOL},
        ),
    )

    sentence = describe_appointment_hours(AppointmentHours())
    assert answers == {"appointment_hours": f"{sentence}\n"}


def test_without_hours_the_field_stays_empty():
    # No calendar, so no hours (and maybe an empty text answer).
    answers = appointment_hours_answers(
        FIELDS, _request(values={"business_name": "Bloom", "appointment_hours": " "})
    )

    assert answers["appointment_hours"] == ""


@pytest.mark.parametrize(
    ("fields", "body", "message"),
    [
        (
            FIELDS[:1],
            {"integration_tools": {"google-calendar": TOOL}},
            "doesn't ask for appointment hours",
        ),
        # Only bookings use the hours, and only Google Calendar books.
        (FIELDS, {}, "need Google Calendar attached"),
        (
            FIELDS,
            {
                "values": {"appointment_hours": "Mon-Fri 9-5"},
                "integration_tools": {"google-calendar": TOOL},
            },
            "not as text",
        ),
    ],
)
def test_rejects_hours_sent_the_wrong_way(fields, body, message):
    with pytest.raises(TemplateSetupError, match=message):
        appointment_hours_answers(fields, _request(appointment_hours={}, **body))


def _receptionist_facts(**body: Any) -> list[str]:
    """The lines of the receptionist's prompt from its opening hours on."""
    (receptionist,) = [t for t in STARTER_TEMPLATES if t.name == "AI Receptionist"]
    fields = receptionist.setup_fields
    values = {f.key: f"Sample {f.key}" for f in fields if f.required}
    request = _request(values=values, **body)

    filled = fill_template_values(
        receptionist.definition,
        fields,
        request.values,
        rendered=appointment_hours_answers(fields, request),
    )
    agent = attach_integration_tools(filled, request.integration_tools)
    validate_workflow_definition(agent)
    assert "{{appointment_hours" not in json.dumps(agent)
    (prompt,) = {
        node["data"]["prompt"]
        for node in agent["nodes"]
        if "Opening hours:" in node["data"].get("prompt", "")
    }
    lines = prompt.splitlines()
    return lines[lines.index("Opening hours: Sample opening_hours") :]


def test_the_receptionist_tells_callers_its_appointment_hours():
    hours = AppointmentHours.model_validate(WEEKEND_MORNINGS)

    facts = _receptionist_facts(
        appointment_hours=WEEKEND_MORNINGS,
        integration_tools={"google-calendar": TOOL},
    )

    assert facts[1] == describe_appointment_hours(hours)
    assert facts[2].startswith("Address: ")


def test_the_receptionist_without_a_calendar_has_no_hours_line():
    facts = _receptionist_facts()

    assert facts[1].startswith("Address: ")


# -- saving the hours to the calendar connection -------------------------------


def _connection(**overrides: Any) -> IntegrationConnectionResponse:
    now = datetime(2026, 10, 1, tzinfo=UTC)
    data: dict[str, Any] = {
        "id": CONNECTION_ID,
        "provider": "google-calendar",
        "auth_mode": "oauth2",
        "config": {"calendar_id": "primary"},
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "tool_uuids": [TOOL],
        **overrides,
    }
    return IntegrationConnectionResponse.model_validate(data)


class FakeCalendarSettings:
    def __init__(
        self,
        connections: list[IntegrationConnectionResponse],
        error: Exception | None = None,
    ) -> None:
        self.connections = connections
        self.error = error
        self.updates: list[tuple[Actor, uuid.UUID, dict[str, Any]]] = []

    async def list_connections(
        self, actor: Actor
    ) -> list[IntegrationConnectionResponse]:
        return self.connections

    async def update_config(
        self, actor: Actor, connection_id: uuid.UUID, config: Any
    ) -> IntegrationConnectionResponse:
        if self.error:
            raise self.error
        self.updates.append((actor, connection_id, dict(config)))
        return self.connections[0]


def _actor() -> Actor:
    return Actor(organization_id=ORG_ID, user=SimpleNamespace(id=1))  # type: ignore[arg-type]


async def _update(
    settings: FakeCalendarSettings,
    *,
    allowed: bool = True,
    **body: Any,
) -> CalendarHoursStatus | None:
    request = _request(
        **{
            "appointment_hours": {},
            "apply_to_calendar": True,
            "integration_tools": {"google-calendar": TOOL},
            **body,
        }
    )
    return await update_calendar_booking_hours(
        request,
        _actor(),
        may_change_settings=allowed,
        calendar_settings=lambda: settings,
    )


async def test_saves_the_hours_to_the_connection_of_the_attached_tool():
    other = _connection(id=uuid.uuid4(), tool_uuids=["another-tool"])
    settings = FakeCalendarSettings([other, _connection()])

    status = await _update(settings)

    assert status is CalendarHoursStatus.UPDATED
    ((actor, connection_id, config),) = settings.updates
    assert actor.organization_id == ORG_ID
    assert connection_id == CONNECTION_ID
    assert config == calendar_config_patch(AppointmentHours())


async def test_hours_the_connection_already_books_in_are_not_saved_again():
    stored = {"calendar_id": "primary", **calendar_config_patch(DEFAULT_HOURS)}
    settings = FakeCalendarSettings([_connection(config=stored)])

    assert await _update(settings) is CalendarHoursStatus.UPDATED
    assert settings.updates == []


@pytest.mark.parametrize(
    "body",
    [
        # Reusing a connection without changing its hours.
        {"apply_to_calendar": False},
        {"appointment_hours": None, "apply_to_calendar": False},
        {"integration_tools": {}},
    ],
)
async def test_nothing_to_save_unless_asked_with_a_calendar(body):
    settings = FakeCalendarSettings([_connection()])

    assert await _update(settings, **body) is None
    assert settings.updates == []


async def test_a_role_that_cannot_change_integrations_leaves_the_calendar_alone():
    settings = FakeCalendarSettings([_connection()])

    status = await _update(settings, allowed=False)

    assert status is CalendarHoursStatus.NOT_ALLOWED
    assert settings.updates == []


@pytest.mark.parametrize(
    "settings",
    [
        # The tool belongs to no calendar connection of this org.
        FakeCalendarSettings([_connection(tool_uuids=["another-tool"])]),
        # The tools service refused the settings.
        FakeCalendarSettings(
            [_connection()], error=IntegrationInvalidRequestError("bad config")
        ),
        # The tools service is down.
        FakeCalendarSettings([_connection()], error=ToolsServiceUnavailableError()),
        # A bug (or the database) after the agent was created: retrying would
        # create the agent twice, so this is reported too.
        FakeCalendarSettings([_connection()], error=KeyError("oops")),
    ],
)
async def test_a_failure_is_reported_not_raised(settings):
    assert await _update(settings) is CalendarHoursStatus.FAILED


async def test_failed_when_the_tools_service_is_not_configured():
    def not_configured() -> FakeCalendarSettings:
        raise ToolsServiceNotConfiguredError()

    status = await update_calendar_booking_hours(
        _request(
            appointment_hours={},
            apply_to_calendar=True,
            integration_tools={"google-calendar": TOOL},
        ),
        _actor(),
        may_change_settings=True,
        calendar_settings=not_configured,
    )

    assert status is CalendarHoursStatus.FAILED


# -- the create-from-template route --------------------------------------------


class FakeResources:
    """The workspace credential and MCP tool installed for the connection."""

    async def list_linked_credentials(
        self, organization_id: int, *, include_deleted: bool = False
    ) -> list[LinkedCredential]:
        assert organization_id == ORG_ID
        return [LinkedCredential("cred-1", CONNECTION_ID, "google-calendar")]

    async def mcp_tools_by_credential(self, organization_id: int):
        assert organization_id == ORG_ID
        return {"cred-1": [TOOL]}


class ToolsServiceStub:
    """The tools service's ``/internal`` API, over a mock HTTP transport."""

    def __init__(self, patch_status: int = 200) -> None:
        self.patch_status = patch_status
        self.requests: list[httpx.Request] = []
        self.config: dict[str, Any] = {
            "calendar_id": "desk@bloom.ie",
            "buffer_minutes": 10,
        }

    def _connection(self) -> dict[str, Any]:
        return _connection(config=self.config).model_dump(
            mode="json", exclude={"credential_uuid", "tool_uuids"}
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "GET" and request.url.path == "/internal/connections":
            return httpx.Response(200, json={"connections": [self._connection()]})
        if request.method == "PATCH":
            if self.patch_status != 200:
                return httpx.Response(self.patch_status, json={"detail": "nope"})
            # Merge, as the tools service does.
            self.config = {**self.config, **json.loads(request.content)["config"]}
            return httpx.Response(200, json=self._connection())
        return httpx.Response(404, json={"detail": "Not found"})

    def service(self) -> IntegrationService:
        return IntegrationService(
            tools_service=ToolsServiceClient(
                base_url=TOOLS_URL,
                internal_secret=SECRET,
                http=httpx.AsyncClient(transport=httpx.MockTransport(self.handle)),
            ),
            resources=FakeResources(),  # type: ignore[arg-type]
            tools_base_url=TOOLS_URL,
        )


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=1, selected_organization_id=ORG_ID
    )
    return TestClient(app)


def _template() -> SimpleNamespace:
    return SimpleNamespace(
        id=3,
        template_name="Reception",
        template_json={
            "nodes": [
                {
                    "data": {
                        "greeting": "Hi, this is {{business_name}}.",
                        "prompt": "Hours: {{appointment_hours}}",
                        "tool_uuids": ["integration:google-calendar"],
                    }
                }
            ]
        },
        setup_fields=[field.model_dump() for field in FIELDS],
        integrations=["google-calendar"],
    )


def _created_workflow() -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        name="Reception",
        status="active",
        created_at=datetime(2026, 10, 19, tzinfo=UTC),
        current_definition_id=7,
        template_context_variables={},
        call_disposition_codes=None,
        workflow_configurations={},
    )


def _duplicate(stub: ToolsServiceStub, **body: Any) -> tuple[Any, Any]:
    with (
        patch("api.routes.workflow.WorkflowTemplateClient") as templates,
        patch("api.routes.workflow.db_client") as db,
        patch.object(hours_module, "get_integration_service", stub.service),
    ):
        templates.return_value.get_workflow_template = AsyncMock(
            return_value=_template()
        )
        db.get_tools_by_uuids = AsyncMock(
            return_value=[SimpleNamespace(tool_uuid=TOOL)]
        )
        db.create_workflow = AsyncMock(return_value=_created_workflow())
        response = _client().post(
            "/workflow/templates/duplicate",
            json={
                "template_id": 3,
                "workflow_name": "Reception",
                "values": {"business_name": "Bloom"},
                **body,
            },
        )
    return response, db


def _prompt(db: Any) -> str:
    return db.create_workflow.await_args.args[1]["nodes"][0]["data"]["prompt"]


CALENDAR = {"google-calendar": TOOL}


def test_route_puts_the_hours_in_the_prompt_and_the_calendar():
    stub = ToolsServiceStub()

    response, db = _duplicate(
        stub,
        appointment_hours=WEEKEND_MORNINGS,
        apply_to_calendar=True,
        integration_tools=CALENDAR,
    )

    assert response.status_code == 200, response.text
    assert response.json()["calendar_hours"] == "updated"
    hours = AppointmentHours.model_validate(WEEKEND_MORNINGS)
    assert _prompt(db) == f"Hours: {describe_appointment_hours(hours)}\n"
    (update,) = [r for r in stub.requests if r.method == "PATCH"]
    assert update.url.path == f"/internal/connections/{CONNECTION_ID}"
    # Org-scoped like every call to the tools service.
    assert update.headers["X-Org-Id"] == str(ORG_ID)
    assert update.headers["X-User-Id"] == "1"
    assert json.loads(update.content) == {"config": calendar_config_patch(hours)}
    # The calendar and its other settings are kept.
    assert stub.config["calendar_id"] == "desk@bloom.ie"
    assert stub.config["buffer_minutes"] == 10
    assert stub.config["open_hour"] == 8


def test_route_tells_the_hours_of_a_reused_calendar_without_saving_them():
    stub = ToolsServiceStub()

    response, db = _duplicate(stub, appointment_hours={}, integration_tools=CALENDAR)

    assert response.status_code == 200, response.text
    assert response.json()["calendar_hours"] is None
    assert "Monday to Friday, 9:00–17:00" in _prompt(db)
    assert stub.requests == []


def test_route_does_not_save_hours_the_calendar_already_books_in():
    stub = ToolsServiceStub()
    stub.config.update(calendar_config_patch(DEFAULT_HOURS))

    response, _ = _duplicate(
        stub, appointment_hours={}, apply_to_calendar=True, integration_tools=CALENDAR
    )

    assert response.json()["calendar_hours"] == "updated"
    assert [r.method for r in stub.requests] == ["GET"]


def test_route_keeps_the_agent_when_the_calendar_refuses_the_hours():
    stub = ToolsServiceStub(patch_status=422)

    response, db = _duplicate(
        stub, appointment_hours={}, apply_to_calendar=True, integration_tools=CALENDAR
    )

    assert response.status_code == 200, response.text
    assert response.json()["id"] == 42
    assert response.json()["calendar_hours"] == "failed"
    db.create_workflow.assert_awaited_once()


def test_route_respects_a_role_that_cannot_change_integrations(monkeypatch):
    real = auth_depends.has_permissions
    monkeypatch.setattr(
        auth_depends,
        "has_permissions",
        lambda role, *wanted: (
            Permission.INTEGRATIONS_WRITE not in wanted and real(role, *wanted)
        ),
    )
    stub = ToolsServiceStub()

    response, _ = _duplicate(
        stub, appointment_hours={}, apply_to_calendar=True, integration_tools=CALENDAR
    )

    assert response.status_code == 200, response.text
    assert response.json()["calendar_hours"] == "not_allowed"
    assert stub.requests == []


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (
            {"appointment_hours": {"timezone": "Not/AZone"}, "apply_to_calendar": True},
            "Unknown time zone",
        ),
        ({"apply_to_calendar": True}, "apply_to_calendar needs"),
    ],
)
def test_route_rejects_bad_hours_before_creating_anything(body, message):
    stub = ToolsServiceStub()

    response, db = _duplicate(stub, integration_tools=CALENDAR, **body)

    assert response.status_code == 422
    assert message in response.text
    db.create_workflow.assert_not_awaited()
    assert stub.requests == []


def test_route_rejects_hours_without_a_calendar():
    response, db = _duplicate(ToolsServiceStub(), appointment_hours={})

    assert response.status_code == 422
    assert "need Google Calendar attached" in response.text
    db.create_workflow.assert_not_awaited()


def test_route_without_hours_leaves_the_placeholder_empty():
    stub = ToolsServiceStub()

    response, db = _duplicate(stub, integration_tools=CALENDAR)

    assert response.status_code == 200, response.text
    assert response.json()["calendar_hours"] is None
    assert _prompt(db) == "Hours: "
    assert stub.requests == []
