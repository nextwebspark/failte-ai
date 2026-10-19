from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.workflow import router
from api.schemas.workflow_template import TemplateSetupField
from api.services.auth.depends import get_user
from api.services.workflow.agent_builder import validate_workflow_definition
from api.services.workflow.starter_templates import STARTER_TEMPLATES
from api.services.workflow.template_setup import (
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
        values = {field.key: f"Sample {field.key}" for field in starter.setup_fields}

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
        assert set(starter.row()) >= {"template_json", "setup_fields", "integrations"}


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
