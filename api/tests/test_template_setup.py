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


def test_starter_templates_fill_into_valid_agents():
    for starter in STARTER_TEMPLATES:
        keys = {field.key for field in starter.setup_fields}
        assert len(keys) == len(starter.setup_fields), starter.name
        values = {field.key: f"Sample {field.key}" for field in starter.setup_fields}

        filled = fill_template_values(starter.definition, starter.setup_fields, values)

        # No setup placeholder is left, and nothing else needs a variable.
        validate_workflow_definition(filled)
        text = str(filled)
        assert "Sample business_name" in text
        for key in keys:
            assert "{{" + key not in text, (starter.name, key)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=1, selected_organization_id=11
    )
    return TestClient(app)


def _template():
    return SimpleNamespace(
        id=3,
        template_name="Reception",
        template_description="Answers calls",
        template_json=DEFINITION,
        setup_fields=[field.model_dump() for field in FIELDS],
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )


def test_duplicate_fills_the_template_with_the_answers():
    created = SimpleNamespace(
        id=42,
        name="Bloom Dental reception",
        status="active",
        created_at=datetime(2026, 10, 19, tzinfo=timezone.utc),
        current_definition_id=7,
        template_context_variables={},
        call_disposition_codes=None,
        workflow_configurations={},
    )
    with (
        patch("api.routes.workflow.WorkflowTemplateClient") as templates,
        patch("api.routes.workflow.db_client") as db,
    ):
        templates.return_value.get_workflow_template = AsyncMock(
            return_value=_template()
        )
        db.create_workflow = AsyncMock(return_value=created)

        response = _client().post(
            "/workflow/templates/duplicate",
            json={
                "template_id": 3,
                "workflow_name": "Bloom Dental reception",
                "values": {"business_name": "Bloom Dental"},
            },
        )

    assert response.status_code == 200, response.text
    saved = db.create_workflow.await_args.args[1]
    assert saved["nodes"][0]["data"]["greeting"] == "Hi, this is Bloom Dental."


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
