import json
import re
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.workflow import router
from api.schemas.workflow_template import TemplateSetupField
from api.services.auth.depends import get_user
from api.services.workflow.agent_builder import validate_workflow_definition
from api.services.workflow.starter_templates import (
    STARTER_TEMPLATES,
    TemplateCategory,
)
from api.services.workflow.template_setup import (
    INTEGRATION_TOOL_PREFIX,
    TemplateSetupError,
    attach_integration_tools,
    fill_template_values,
)

FIELDS = [
    TemplateSetupField(key="business_name", label="Business name"),
    TemplateSetupField(key="address", label="Address", required=False),
    TemplateSetupField(key="notes", label="Notes", required=False, max_length=5),
]
DEFINITION = {
    "nodes": [
        {
            "data": {
                "greeting": "Hi, this is {{ business_name }}.",
                "prompt": "Address: {{address | fallback:not listed}}. "
                "Notes: {{notes}}. Caller: {{first_name}}.",
            }
        }
    ],
    "viewport": {"zoom": 0.75},
}


def test_fills_answers_and_leaves_other_variables():
    filled = fill_template_values(
        DEFINITION, FIELDS, {"business_name": " Bloom Dental "}
    )

    data = filled["nodes"][0]["data"]
    assert data["greeting"] == "Hi, this is Bloom Dental."
    # Empty optional answers use the fallback, or nothing.
    assert data["prompt"] == "Address: not listed. Notes: . Caller: {{first_name}}."
    assert filled["viewport"] == {"zoom": 0.75}
    # The template itself is untouched.
    assert (
        DEFINITION["nodes"][0]["data"]["greeting"] == "Hi, this is {{ business_name }}."
    )


def test_an_answer_cannot_open_a_placeholder():
    filled = fill_template_values(
        DEFINITION, FIELDS, {"business_name": "{{{secret}}}", "address": "1 Main St"}
    )

    data = filled["nodes"][0]["data"]
    assert data["greeting"] == "Hi, this is {secret}."
    assert data["prompt"].startswith("Address: 1 Main St.")


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({}, "Business name is required."),
        ({"business_name": "   "}, "Business name is required."),
        ({"business_name": "A", "notes": "too long"}, "Notes is too long"),
        ({"business_name": "A", "colour": "red"}, "Unknown setup fields: colour"),
    ],
)
def test_rejects_bad_answers(values, message):
    with pytest.raises(TemplateSetupError, match=message):
        fill_template_values(DEFINITION, FIELDS, values)


def test_rendered_answers_are_used_as_given_but_still_plain_text():
    filled = fill_template_values(
        DEFINITION,
        FIELDS,
        {"business_name": "Bloom", "address": "typed by the user"},
        rendered={"address": "{{secret}} Main St\n"},
    )

    # Over the typed answer, untrimmed, and unable to open a placeholder.
    assert filled["nodes"][0]["data"]["prompt"].startswith(
        "Address: {secret} Main St\n."
    )


def test_rendered_answers_are_length_checked():
    with pytest.raises(TemplateSetupError, match="Notes is too long"):
        fill_template_values(
            DEFINITION, FIELDS, {"business_name": "A"}, rendered={"notes": "too long"}
        )


def test_attach_integration_tools_swaps_or_drops_placeholders():
    definition = {
        "nodes": [
            {"id": "a", "data": {"tool_uuids": ["integration:google-calendar", "t-1"]}},
            {"id": "b", "data": {"prompt": "no tools"}},
        ]
    }

    connected = attach_integration_tools(definition, {"google-calendar": "cal-9"})
    skipped = attach_integration_tools(definition, {})

    assert connected["nodes"][0]["data"]["tool_uuids"] == ["cal-9", "t-1"]
    assert skipped["nodes"][0]["data"]["tool_uuids"] == ["t-1"]
    assert connected["nodes"][1] == definition["nodes"][1]


def test_starter_templates_fill_into_valid_agents():
    for starter in STARTER_TEMPLATES:
        keys = {field.key for field in starter.setup_fields}
        assert len(keys) == len(starter.setup_fields), starter.name
        values = {
            field.key: f"Sample {field.key}"
            for field in starter.setup_fields
            if field.type != "toggles"
        }

        filled = fill_template_values(starter.definition, starter.setup_fields, values)

        for tools in ({}, {provider: "tool-1" for provider in starter.integrations}):
            agent = attach_integration_tools(filled, tools)
            # No setup placeholder is left, and nothing else needs a variable.
            validate_workflow_definition(agent)
            text = str(agent)
            assert "Sample business_name" in text
            assert "integration:" not in text, starter.name
            for key in keys:
                assert "{{" + key not in text, (starter.name, key)
        assert set(starter.row()) >= {
            "template_json",
            "setup_fields",
            "integrations",
            "category",
        }


def test_every_starter_question_is_used_by_its_agent():
    # A question the agent never uses is wasted effort and data we don't need.
    for starter in STARTER_TEMPLATES:
        text = json.dumps(starter.definition)
        for field in starter.setup_fields:
            assert re.search(r"\{\{\s*" + re.escape(field.key) + r"\b", text), (
                starter.name,
                field.key,
            )


def test_starter_catalogue_is_consistent():
    names = [starter.name for starter in STARTER_TEMPLATES]
    # The sync upserts by name, so a duplicate would overwrite another starter.
    assert len(names) == len(set(names))
    assert [s.name for s in STARTER_TEMPLATES if s.featured] == ["AI Receptionist"]
    categories = set(get_args(TemplateCategory))
    for starter in STARTER_TEMPLATES:
        assert starter.category in categories, starter.name
        assert starter.row()["category"] == starter.category
        # Templates that offer a calendar must carry the placeholder tool.
        has_placeholder = INTEGRATION_TOOL_PREFIX in str(starter.definition)
        assert has_placeholder == bool(starter.integrations), starter.name


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=1, selected_organization_id=11
    )
    return TestClient(app)


def _template():
    definition = {
        **DEFINITION,
        "nodes": [
            {
                **DEFINITION["nodes"][0],
                "data": {
                    **DEFINITION["nodes"][0]["data"],
                    "tool_uuids": ["integration:google-calendar"],
                },
            }
        ],
    }
    return SimpleNamespace(
        id=3,
        template_name="Reception",
        template_description="Answers calls",
        template_json=definition,
        setup_fields=[field.model_dump() for field in FIELDS],
        call_type="inbound",
        icon="phone",
        featured=True,
        sample_audio_url=None,
        category="clinic",
        integrations=["google-calendar"],
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )


def _created_workflow():
    return SimpleNamespace(
        id=42,
        name="Bloom Dental reception",
        status="active",
        created_at=datetime(2026, 10, 19, tzinfo=timezone.utc),
        current_definition_id=7,
        template_context_variables={},
        call_disposition_codes=None,
        workflow_configurations={},
    )


def test_duplicate_fills_the_template_with_the_answers():
    with (
        patch("api.routes.workflow.WorkflowTemplateClient") as templates,
        patch("api.routes.workflow.db_client") as db,
    ):
        templates.return_value.get_workflow_template = AsyncMock(
            return_value=_template()
        )
        db.create_workflow = AsyncMock(return_value=_created_workflow())

        response = _client().post(
            "/workflow/templates/duplicate",
            json={
                "template_id": 3,
                "workflow_name": "Bloom Dental reception",
                "values": {"business_name": "Bloom Dental"},
            },
        )

    assert response.status_code == 200, response.text
    data = db.create_workflow.await_args.args[1]["nodes"][0]["data"]
    assert data["greeting"] == "Hi, this is Bloom Dental."
    # No calendar connected: the step keeps no calendar tool.
    assert data["tool_uuids"] == []


def test_duplicate_attaches_the_connected_calendar():
    with (
        patch("api.routes.workflow.WorkflowTemplateClient") as templates,
        patch("api.routes.workflow.db_client") as db,
    ):
        templates.return_value.get_workflow_template = AsyncMock(
            return_value=_template()
        )
        db.get_tools_by_uuids = AsyncMock(
            return_value=[SimpleNamespace(tool_uuid="cal-9")]
        )
        db.create_workflow = AsyncMock(return_value=_created_workflow())

        response = _client().post(
            "/workflow/templates/duplicate",
            json={
                "template_id": 3,
                "workflow_name": "Reception",
                "values": {"business_name": "Bloom Dental"},
                "integration_tools": {"google-calendar": "cal-9"},
            },
        )

    assert response.status_code == 200, response.text
    db.get_tools_by_uuids.assert_awaited_once_with(["cal-9"], 11)
    data = db.create_workflow.await_args.args[1]["nodes"][0]["data"]
    assert data["tool_uuids"] == ["cal-9"]


@pytest.mark.parametrize(
    ("integration_tools", "found", "status"),
    [
        ({"outlook": "x"}, [], 422),
        ({"google-calendar": "someone-elses"}, [], 404),
    ],
)
def test_duplicate_rejects_a_bad_integration_tool(integration_tools, found, status):
    with (
        patch("api.routes.workflow.WorkflowTemplateClient") as templates,
        patch("api.routes.workflow.db_client") as db,
    ):
        templates.return_value.get_workflow_template = AsyncMock(
            return_value=_template()
        )
        db.get_tools_by_uuids = AsyncMock(return_value=found)
        db.create_workflow = AsyncMock()

        response = _client().post(
            "/workflow/templates/duplicate",
            json={
                "template_id": 3,
                "workflow_name": "Reception",
                "values": {"business_name": "Bloom Dental"},
                "integration_tools": integration_tools,
            },
        )

    assert response.status_code == status
    db.create_workflow.assert_not_awaited()


def test_duplicate_rejects_a_missing_answer():
    with (
        patch("api.routes.workflow.WorkflowTemplateClient") as templates,
        patch("api.routes.workflow.db_client") as db,
    ):
        templates.return_value.get_workflow_template = AsyncMock(
            return_value=_template()
        )
        db.create_workflow = AsyncMock()

        response = _client().post(
            "/workflow/templates/duplicate",
            json={"template_id": 3, "workflow_name": "Reception", "values": {}},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Business name is required."
    db.create_workflow.assert_not_awaited()


def test_templates_list_includes_setup_fields():
    with patch("api.routes.workflow.WorkflowTemplateClient") as templates:
        templates.return_value.get_all_workflow_templates = AsyncMock(
            return_value=[_template()]
        )
        response = _client().get("/workflow/templates")

    assert response.status_code == 200
    fields = response.json()[0]["setup_fields"]
    assert [field["key"] for field in fields] == ["business_name", "address", "notes"]
    assert fields[0]["required"] is True
    template = response.json()[0]
    assert template["integrations"] == ["google-calendar"]
    assert template["featured"] is True
    assert template["call_type"] == "inbound"
    assert template["category"] == "clinic"


def _captured(starter_name: str) -> list[str]:
    starter = next(s for s in STARTER_TEMPLATES if s.name == starter_name)
    for node in starter.definition["nodes"]:
        variables = node["data"].get("extraction_variables")
        if variables:
            return [v["name"] for v in variables]
    return []


def test_booking_templates_record_the_booking_details():
    assert _captured("Restaurant bookings") == [
        "caller_name",
        "callback_number",
        "call_reason",
        "booking_outcome",
        "booking_date",
        "booking_time",
        "party_size",
        "special_requests",
    ]
    assert {"appointment_type", "patient_status"} <= set(
        _captured("Clinic receptionist")
    )
    assert {"service", "stylist"} <= set(_captured("Salon receptionist"))
    assert "property" in _captured("Estate viewing booker")
    assert {"job_address", "urgency"} <= set(_captured("Trades after-hours"))


def test_booking_templates_ask_check_read_back_and_hand_off():
    for starter in STARTER_TEMPLATES:
        if "booking_outcome" not in _captured(starter.name):
            continue
        text = json.dumps(starter.definition)
        if starter.name == "Appointment reminder":
            continue  # moves an existing booking; it does not take new ones
        assert "Check availability" in text, starter.name
        assert "read it all back in one sentence" in text, starter.name
        assert "handoff" in text and "transfer them to the team" in text, starter.name
        assert "unless the calendar confirmed it" in text, starter.name
    restaurant = json.dumps(
        next(s for s in STARTER_TEMPLATES if s.name == "Restaurant bookings").definition
    )
    assert "{{booking_questions}}" in restaurant
    assert "a mobile number" in restaurant


def test_generated_agents_keep_the_five_field_limit():
    from api.services.workflow.agent_builder import (
        MAX_CAPTURED_FIELDS,
        AgentSpec,
        CapturedFieldSpec,
        StageSpec,
        assemble_workflow_definition,
    )

    spec = AgentSpec(
        name="Test agent",
        persona="You are a test agent.",
        greeting="Hello.",
        opening=StageSpec(name="Talk", prompt="Talk to them.", done_when="Done."),
        stages=[StageSpec(name="Wrap up", prompt="Wrap up.", done_when="Done.")],
        closing_prompt="Say goodbye.",
        end_call_when="They hang up.",
        captured_fields=[
            CapturedFieldSpec(name=f"field_{i}", description=f"Field {i}.")
            for i in range(8)
        ],
    )

    def count(definition: dict) -> int:
        for node in definition["nodes"]:
            variables = node["data"].get("extraction_variables")
            if variables:
                return len(variables)
        return 0

    assert count(assemble_workflow_definition(spec, "INBOUND")) == MAX_CAPTURED_FIELDS
    assert (
        count(assemble_workflow_definition(spec, "INBOUND", max_captured_fields=8)) == 8
    )


def _restaurant():
    return next(s for s in STARTER_TEMPLATES if s.name == "Restaurant bookings")


def _ask_line(definition: dict) -> str:
    prompt = next(
        n["data"]["prompt"] for n in definition["nodes"] if n["id"] == "start"
    )
    return next(line for line in prompt.splitlines() if line.startswith("1. Ask"))


def _business_answers(starter) -> dict[str, str]:
    return {f.key: "Sample" for f in starter.setup_fields if f.type != "toggles"}


def test_booking_toggles_default_to_the_usual_questions():
    starter = _restaurant()
    filled = fill_template_values(
        starter.definition, starter.setup_fields, _business_answers(starter)
    )
    assert _ask_line(filled).endswith(
        "Also ask how many people and about any allergies or dietary needs."
    )


def test_booking_toggles_follow_the_owners_choice():
    starter = _restaurant()
    answers = {
        **_business_answers(starter),
        "booking_questions": "high_chair,party_size,occasion",
    }
    line = _ask_line(
        fill_template_values(starter.definition, starter.setup_fields, answers)
    )
    # Option order, not click order.
    assert line.endswith(
        "Also ask how many people, whether it is for a special occasion and "
        "whether they need a high chair."
    )


def test_all_toggles_off_asks_only_the_essentials():
    starter = _restaurant()
    answers = {**_business_answers(starter), "booking_questions": ""}
    line = _ask_line(
        fill_template_values(starter.definition, starter.setup_fields, answers)
    )
    assert "Also ask" not in line
    assert "the day, the time, the name for the booking and a mobile number" in line


def test_unknown_toggle_is_rejected():
    starter = _restaurant()
    answers = {**_business_answers(starter), "booking_questions": "party_size,wine"}
    with pytest.raises(TemplateSetupError, match="unknown choice wine"):
        fill_template_values(starter.definition, starter.setup_fields, answers)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ({"key": "q", "label": "Q", "type": "toggles"}, "needs options"),
        (
            {
                "key": "q",
                "label": "Q",
                "type": "text",
                "options": [{"value": "a", "label": "A", "prompt": "a"}],
            },
            "only a toggles question has options",
        ),
        (
            {
                "key": "q",
                "label": "Q",
                "type": "toggles",
                "sentence": "Ask these.",
                "options": [{"value": "a", "label": "A", "prompt": "a"}],
            },
            "must contain {items}",
        ),
    ],
)
def test_toggle_questions_are_validated(field, message):
    with pytest.raises(ValueError, match=message):
        TemplateSetupField.model_validate(field)


def test_every_booking_starter_offers_toggles():
    for starter in STARTER_TEMPLATES:
        uses = "{{booking_questions}}" in json.dumps(starter.definition)
        offers = any(f.key == "booking_questions" for f in starter.setup_fields)
        assert uses == offers, starter.name


def test_agents_check_the_caller_before_changing_a_booking():
    # Earlier bookings are found with find_appointments: the booked name is
    # always asked, the number comes from caller ID or the caller (the owner
    # must allow changes). Without a match, nothing changes.
    for starter in STARTER_TEMPLATES:
        text = json.dumps(starter.definition)
        assert "find_booking" not in text and "move_appointment" not in text
        if "{{booking_questions}}" in text:
            assert "find_appointments" in text, starter.name
            assert "reschedule_appointment" in text, starter.name
            assert "full name the booking was made under" in text, starter.name
            assert "Never guess a booking" in text, starter.name
            assert "Never say a booking is moved or cancelled" in text, starter.name
        assert "update the booking" not in text, starter.name
        assert "reschedule via calendar tools" not in text, starter.name
