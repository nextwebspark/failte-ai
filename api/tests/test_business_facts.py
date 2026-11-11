"""Business facts: kept on the agent at creation, read at call time, editable
by the owner without the agent editor."""

import pytest

from api.schemas.workflow_template import TemplateSetupField
from api.services.workflow.business_facts import (
    BusinessFactsError,
    checked_updates,
    fact_fields,
)
from api.services.workflow.starter_templates import STARTER_TEMPLATES
from api.services.workflow.template_setup import fill_template
from api.utils.template_renderer import render_template


def _restaurant():
    return next(s for s in STARTER_TEMPLATES if s.name == "Restaurant bookings")


def _answers(starter):
    return {
        "business_name": "Harbour Kitchen",
        "business_description": "Seafood in Galway.",
        "opening_hours": "Tue-Sun 12-22",
        "address": "1 Quay St, Galway",
        "booking_questions": "party_size",
    }


def _start_prompt(definition):
    return next(n["data"]["prompt"] for n in definition["nodes"] if n["id"] == "start")


def test_creating_from_a_template_keeps_the_facts_on_the_agent():
    starter = _restaurant()
    definition, facts = fill_template(
        starter.definition, starter.setup_fields, _answers(starter)
    )
    assert facts == {
        "business_name": "Harbour Kitchen",
        "business_description": "Seafood in Galway.",
        "opening_hours": "Tue-Sun 12-22",
        "address": "1 Quay St, Galway",
    }
    text = str(definition)
    assert "Tue-Sun 12-22" not in text  # not written into the prompts
    assert "{{initial_context.opening_hours}}" in text
    # Unanswered optional facts keep their fallback for the call.
    assert "{{initial_context.website | fallback:" in text
    # Toggle answers are still written in.
    assert "Also ask how many people." in _start_prompt(definition)


def test_the_call_reads_the_current_facts():
    starter = _restaurant()
    definition, facts = fill_template(
        starter.definition, starter.setup_fields, _answers(starter)
    )
    persona = next(n for n in definition["nodes"] if n["id"] == "global")["data"][
        "prompt"
    ]
    rendered = render_template(persona, {**facts, "opening_hours": "Wed-Sun 17-23"})
    assert "Wed-Sun 17-23" in rendered
    assert "Harbour Kitchen" in rendered
    assert "{{" not in rendered


def test_the_agent_lists_its_facts_with_labels_and_values():
    starter = _restaurant()
    definition, facts = fill_template(
        starter.definition, starter.setup_fields, _answers(starter)
    )
    fields = fact_fields(definition, facts)
    by_key = {f.key: f for f in fields}
    assert list(by_key)[:3] == [
        "business_name",
        "business_description",
        "opening_hours",
    ]
    assert by_key["opening_hours"].value == "Tue-Sun 12-22"
    assert by_key["opening_hours"].label == "Opening hours"
    assert by_key["website"].value == ""
    assert "caller_number" not in by_key


def test_owner_edits_are_checked():
    fields = fact_fields(
        {
            "p": "{{initial_context.opening_hours}} {{initial_context.website | fallback:none}}"
        },
        {"opening_hours": "9-5"},
        questions={
            "opening_hours": TemplateSetupField(
                key="opening_hours", label="Opening hours", stored=True
            ),
            "website": TemplateSetupField(
                key="website",
                label="Website",
                required=False,
                max_length=20,
                stored=True,
            ),
        },
    )
    assert checked_updates(fields, {"opening_hours": " 10-6 ", "website": ""}) == {
        "opening_hours": "10-6",
        "website": None,
    }
    assert checked_updates(fields, {"opening_hours": "{{secret}}"}) == {
        "opening_hours": "{secret}"
    }
    with pytest.raises(BusinessFactsError, match="can't be empty"):
        checked_updates(fields, {"opening_hours": "  "})
    with pytest.raises(BusinessFactsError, match="too long"):
        checked_updates(fields, {"website": "x" * 21})
    with pytest.raises(BusinessFactsError, match="no fact: caller_number"):
        checked_updates(fields, {"caller_number": "123"})


def test_inbound_templates_can_put_callers_through_to_a_person():
    from api.services.workflow.template_setup import BUILTIN_TRANSFER_TOOL

    for starter in STARTER_TEMPLATES:
        has_question = any(f.key == "transfer_number" for f in starter.setup_fields)
        assert has_question is (starter.call_type == "inbound"), starter.name
        if starter.call_type == "inbound":
            assert BUILTIN_TRANSFER_TOOL in str(starter.definition), starter.name

    starter = _restaurant()
    definition, facts = fill_template(
        starter.definition,
        starter.setup_fields,
        {**_answers(starter), "transfer_number": "+353 87 123 4567"},
    )
    assert facts["transfer_number"] == "+353 87 123 4567"
    persona = next(n for n in definition["nodes"] if n["id"] == "global")["data"][
        "prompt"
    ]
    on = render_template(persona, facts)
    off = render_template(
        persona, {k: v for k, v in facts.items() if k != "transfer_number"}
    )
    assert "Never read that number out" in on
    assert "Putting callers through to a person: not available." in off


def test_the_placeholder_becomes_the_agents_transfer_tool():
    from api.services.workflow.template_setup import (
        BUILTIN_TRANSFER_TOOL,
        attach_tool_placeholder,
        uses_tool_placeholder,
    )

    definition = {
        "nodes": [
            {"id": "a", "data": {"tool_uuids": ["cal", BUILTIN_TRANSFER_TOOL]}},
            {"id": "b", "data": {}},
        ]
    }
    assert uses_tool_placeholder(definition, BUILTIN_TRANSFER_TOOL)
    swapped = attach_tool_placeholder(definition, BUILTIN_TRANSFER_TOOL, "t-1")
    assert swapped["nodes"][0]["data"]["tool_uuids"] == ["cal", "t-1"]
    dropped = attach_tool_placeholder(definition, BUILTIN_TRANSFER_TOOL, None)
    assert dropped["nodes"][0]["data"]["tool_uuids"] == ["cal"]
    assert not uses_tool_placeholder(swapped, BUILTIN_TRANSFER_TOOL)


def test_duplicating_creates_one_transfer_tool_for_the_agent():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routes.workflow import router
    from api.services.auth.depends import get_user

    starter = _restaurant()
    template = SimpleNamespace(
        id=5,
        template_name=starter.name,
        template_description=starter.description,
        template_json=starter.definition,
        setup_fields=[f.model_dump() for f in starter.setup_fields],
        call_type="inbound",
        icon="utensils",
        featured=False,
        sample_audio_url=None,
        category="restaurant",
        integrations=starter.integrations,
        created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    created = SimpleNamespace(
        id=42,
        name="Harbour Kitchen",
        status="active",
        created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        current_definition_id=7,
        template_context_variables={},
        call_disposition_codes=None,
        workflow_configurations={},
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=1, selected_organization_id=11
    )
    with (
        patch("api.routes.workflow.WorkflowTemplateClient") as templates,
        patch("api.routes.workflow.db_client") as db,
    ):
        templates.return_value.get_workflow_template = AsyncMock(return_value=template)
        db.create_tool = AsyncMock(return_value=SimpleNamespace(tool_uuid="transfer-1"))
        db.create_workflow = AsyncMock(return_value=created)
        response = TestClient(app).post(
            "/workflow/templates/duplicate",
            json={
                "template_id": 5,
                "workflow_name": "Harbour Kitchen",
                "values": {**_answers(starter), "transfer_number": "+353871234567"},
            },
        )

    assert response.status_code == 200, response.text
    kwargs = db.create_tool.await_args.kwargs
    assert kwargs["category"] == "transfer_call"
    assert kwargs["definition"]["config"]["destination"] == (
        "{{initial_context.transfer_number}}"
    )
    definition = db.create_workflow.await_args.args[1]
    start = next(n for n in definition["nodes"] if n["id"] == "start")
    assert "transfer-1" in start["data"]["tool_uuids"]
    facts = db.create_workflow.await_args.kwargs["template_context_variables"]
    assert facts["transfer_number"] == "+353871234567"
    assert facts["opening_hours"] == "Tue-Sun 12-22"
    # The call review words what callers wanted for this kind of business.
    assert facts["template_category"] == "restaurant"


def test_examples_follow_the_agents_kind_of_business():
    from api.services.workflow.business_facts import known_fact_questions

    restaurant = known_fact_questions("restaurant")
    assert restaurant["website"].placeholder == "https://harbourkitchen.ie"
    # A general agent (or one whose template is unknown) never sees another
    # business's examples, such as the dental practice's.
    general = known_fact_questions("general")
    assert general["website"].placeholder == "https://yourbusiness.ie"
    assert general["business_name"].placeholder is None
    assert general["opening_hours"].placeholder
