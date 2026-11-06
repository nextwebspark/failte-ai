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
