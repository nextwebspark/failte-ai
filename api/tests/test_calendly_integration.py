"""Calendly in the API: the event-type choices proxy (tools service mocked
with httpx) and Calendly standing in for Google Calendar in templates. No
database needed."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from api.errors.integrations import (
    IntegrationConflictError,
    IntegrationNotFoundError,
)
from api.schemas.integrations import IntegrationChoiceListResponse
from api.services.tool_integrations.client import Caller, ToolsServiceClient
from api.services.tool_integrations.service import Actor, IntegrationService
from api.services.workflow.appointment_hours import appointment_hours_answers
from api.services.workflow.template_setup import (
    CALENDLY,
    GOOGLE_CALENDAR,
    INTEGRATION_TOOL_PREFIX,
    TemplateSetupError,
    allowed_integrations,
    attach_integration_tools,
    check_integration_tools,
)

TOOLS_URL = "http://tools.test"
SECRET = "internal-secret-for-tests-0123456789"
EVENT_TYPE = "https://api.calendly.com/event_types/ET-1"
CHOICES = {
    "field": "event_type",
    "choices": [
        {
            "value": EVENT_TYPE,
            "label": "Consultation",
            "detail": "30 minutes",
            "warning": None,
            "config": {"event_type": EVENT_TYPE, "event_type_name": "Consultation"},
        }
    ],
}


def _client(handler) -> ToolsServiceClient:
    return ToolsServiceClient(
        base_url=TOOLS_URL,
        internal_secret=SECRET,
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_client_reads_choices_with_the_internal_identity():
    connection_id = uuid.uuid4()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=CHOICES)

    found = await _client(handler).list_choices(
        Caller(org_id=3, user_id=9), connection_id
    )
    assert isinstance(found, IntegrationChoiceListResponse)
    assert found.field == "event_type"
    assert found.choices[0].config["event_type"] == EVENT_TYPE
    [request] = seen
    assert request.method == "GET"
    assert request.url.path == f"/internal/connections/{connection_id}/choices"
    assert request.headers["X-Internal-Secret"] == SECRET
    assert request.headers["X-Org-Id"] == "3"
    assert request.headers["X-User-Id"] == "9"


@pytest.mark.parametrize(
    ("status", "error"),
    [(409, IntegrationConflictError), (404, IntegrationNotFoundError)],
)
async def test_client_maps_choice_errors(status, error):
    client = _client(
        lambda _: httpx.Response(status, json={"detail": "Calendly is down"})
    )
    with pytest.raises(error, match="Calendly is down"):
        await client.list_choices(Caller(org_id=1, user_id=2), uuid.uuid4())


class _FakeTools:
    def __init__(self) -> None:
        self.calls: list[tuple[Caller, uuid.UUID]] = []

    async def list_choices(self, caller: Caller, connection_id: uuid.UUID):
        self.calls.append((caller, connection_id))
        return IntegrationChoiceListResponse.model_validate(CHOICES)


async def test_service_lists_choices_for_the_acting_org():
    tools = _FakeTools()
    service = IntegrationService(
        tools_service=tools,  # type: ignore[arg-type]
        resources=SimpleNamespace(),  # type: ignore[arg-type]
        tools_base_url=TOOLS_URL,
    )
    connection_id = uuid.uuid4()
    actor = Actor(organization_id=5, user=SimpleNamespace(id=11))  # type: ignore[arg-type]
    found = await service.list_choices(actor, connection_id)
    assert [c.label for c in found.choices] == ["Consultation"]
    assert tools.calls == [(Caller(org_id=5, user_id=11), connection_id)]


# -- templates: Calendly in place of Google Calendar -------------------------------


def _definition() -> dict[str, Any]:
    return {
        "nodes": [
            {
                "data": {
                    "tool_uuids": [
                        f"{INTEGRATION_TOOL_PREFIX}{GOOGLE_CALENDAR}",
                        "transfer-tool",
                    ]
                }
            },
            {"data": {"prompt": "no tools here"}},
        ]
    }


def test_calendly_is_allowed_where_google_calendar_is():
    assert allowed_integrations([GOOGLE_CALENDAR]) == {GOOGLE_CALENDAR, CALENDLY}
    assert allowed_integrations([]) == set()
    check_integration_tools([GOOGLE_CALENDAR], {CALENDLY: "tool-c"})
    check_integration_tools([GOOGLE_CALENDAR], {GOOGLE_CALENDAR: "tool-g"})


def test_unknown_or_two_calendars_are_refused():
    with pytest.raises(TemplateSetupError, match="doesn't use: calendly"):
        check_integration_tools([], {CALENDLY: "tool-c"})
    with pytest.raises(TemplateSetupError, match="Pick one calendar"):
        check_integration_tools(
            [GOOGLE_CALENDAR], {GOOGLE_CALENDAR: "tool-g", CALENDLY: "tool-c"}
        )


def test_calendly_tool_fills_the_google_calendar_placeholder():
    filled = attach_integration_tools(_definition(), {CALENDLY: "tool-c"})
    assert filled["nodes"][0]["data"]["tool_uuids"] == ["tool-c", "transfer-tool"]
    google = attach_integration_tools(_definition(), {GOOGLE_CALENDAR: "tool-g"})
    assert google["nodes"][0]["data"]["tool_uuids"] == ["tool-g", "transfer-tool"]
    none = attach_integration_tools(_definition(), {})
    assert none["nodes"][0]["data"]["tool_uuids"] == ["transfer-tool"]


def test_appointment_hours_are_only_for_google_calendar():
    """Calendly keeps its own availability: the wizard's hours don't apply."""
    from api.schemas.workflow_template import (
        DuplicateTemplateRequest,
        SetupFieldType,
        TemplateSetupField,
    )

    field = TemplateSetupField(
        key="appointment_hours",
        label="Appointment hours",
        type=SetupFieldType.APPOINTMENT_HOURS,
        required=False,
    )
    request = DuplicateTemplateRequest(
        template_id=1,
        workflow_name="Clinic",
        integration_tools={CALENDLY: "tool-c"},
        appointment_hours={
            "booking_days": [0, 1, 2, 3, 4],
            "open_hour": 9,
            "close_hour": 17,
            "slot_minutes": 30,
            "timezone": "Europe/Dublin",
        },
    )
    with pytest.raises(TemplateSetupError, match="Google Calendar"):
        appointment_hours_answers([field], request)
    without_hours = DuplicateTemplateRequest(
        template_id=1, workflow_name="Clinic", integration_tools={CALENDLY: "tool-c"}
    )
    assert appointment_hours_answers([field], without_hours) == {
        "appointment_hours": ""
    }
