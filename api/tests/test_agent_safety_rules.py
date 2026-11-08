"""The fixed rules every inbound starter carries (emergencies, gas, Eircodes,
languages, ending the call) and the "Languages your agent speaks" fact."""

import pytest

from api.services.pronunciation.irish import respell
from api.services.workflow.agent_builder import VOICE_RULES
from api.services.workflow.agent_languages import (
    AGENT_LANGUAGES_KEY,
    AgentLanguagesError,
    agent_language_codes,
    language_name,
    normalised_agent_languages,
    speaks,
)
from api.services.workflow.business_facts import (
    BusinessFactsError,
    checked_updates,
    fact_fields,
)
from api.services.workflow.starter_templates import (
    GAS_EMERGENCY_NUMBER,
    STARTER_TEMPLATES,
    with_current_safety_rules,
)
from api.services.workflow.template_setup import TemplateSetupError, fill_template
from api.utils.template_renderer import render_template


def _global_prompt(definition):
    return next(n for n in definition["nodes"] if n["id"] == "global")["data"]["prompt"]


INBOUND = [s for s in STARTER_TEMPLATES if s.call_type == "inbound"]


@pytest.mark.parametrize("starter", INBOUND, ids=lambda s: s.name)
def test_every_inbound_starter_has_the_safety_rules(starter):
    prompt = _global_prompt(starter.definition)
    assert "Please hang up now and dial 112 or 999." in prompt
    assert "don't assess" in prompt and "end_call" in prompt
    assert GAS_EMERGENCY_NUMBER == "1800 20 50 50"
    assert GAS_EMERGENCY_NUMBER in prompt
    assert "1, 8, 0, 0, 2, 0, 5, 0, 5, 0" in prompt
    assert "{{agent_languages | fallback:English}}" in prompt
    assert "Dia duit" in prompt
    assert any(f.key == AGENT_LANGUAGES_KEY for f in starter.setup_fields)


@pytest.mark.parametrize("starter", INBOUND, ids=lambda s: s.name)
def test_address_taking_starters_ask_for_the_eircode(starter):
    prompt = _global_prompt(starter.definition)
    if starter.category in ("trades", "estate"):
        assert "Eircode" in prompt
        assert "one character at a time" in prompt
        assert "don't know it" in prompt
    else:
        assert "## Addresses" not in prompt


def test_every_starter_ends_the_call_with_the_tool():
    assert "use the end_call or finish_call tool" in VOICE_RULES
    for starter in STARTER_TEMPLATES:
        assert "Never say goodbye and leave the line open." in _global_prompt(
            starter.definition
        ), starter.name


def test_the_clinic_no_longer_takes_a_message_in_an_emergency():
    (clinic,) = [s for s in STARTER_TEMPLATES if s.name == "Clinic receptionist"]
    prompt = _global_prompt(clinic.definition)
    assert "then offer to take a message" not in prompt
    assert "no message, no booking" in prompt


def test_languages_are_english_only_by_default():
    (restaurant,) = [s for s in STARTER_TEMPLATES if s.name == "Restaurant bookings"]
    values = {"business_name": "X", "business_description": "Y", "opening_hours": "Z"}
    definition, facts = fill_template(
        restaurant.definition, restaurant.setup_fields, values
    )
    assert AGENT_LANGUAGES_KEY not in facts
    prompt = render_template(_global_prompt(definition), {})
    assert "You speak: English." in prompt


def test_an_owner_can_switch_on_polish():
    (restaurant,) = [s for s in STARTER_TEMPLATES if s.name == "Restaurant bookings"]
    values = {
        "business_name": "X",
        "business_description": "Y",
        "opening_hours": "Z",
        AGENT_LANGUAGES_KEY: "pl, en",
    }
    definition, facts = fill_template(
        restaurant.definition, restaurant.setup_fields, values
    )
    assert facts[AGENT_LANGUAGES_KEY] == "English, Polish"
    prompt = render_template(_global_prompt(definition), facts)
    assert "You speak: English, Polish." in prompt

    fields = fact_fields(definition, facts)
    (languages,) = [f for f in fields if f.key == AGENT_LANGUAGES_KEY]
    assert languages.type == "languages"
    assert languages.label == "Languages your agent speaks"
    assert checked_updates(fields, {AGENT_LANGUAGES_KEY: "Spanish,polish"}) == {
        AGENT_LANGUAGES_KEY: "English, Polish, Spanish"
    }
    # English only clears the fact, so the prompt's fallback applies.
    assert checked_updates(fields, {AGENT_LANGUAGES_KEY: "English"}) == {
        AGENT_LANGUAGES_KEY: None
    }
    with pytest.raises(BusinessFactsError):
        checked_updates(fields, {AGENT_LANGUAGES_KEY: "Klingon"})
    with pytest.raises(TemplateSetupError):
        fill_template(
            restaurant.definition,
            restaurant.setup_fields,
            {**values, AGENT_LANGUAGES_KEY: "Klingon"},
        )


def test_language_helpers():
    assert normalised_agent_languages(None) is None
    assert normalised_agent_languages("ga,ar,zh") == "English, Irish, Chinese, Arabic"
    with pytest.raises(AgentLanguagesError):
        normalised_agent_languages("German")
    assert agent_language_codes(None) == ["en"]
    assert agent_language_codes("English, Polish, nonsense") == ["en", "pl"]
    assert speaks(None, "en") and speaks("English, Polish", "pl-PL")
    assert not speaks(None, "pl") and not speaks("English, Polish", "pt")
    assert language_name("pl") == "Polish" and language_name("pt-BR") == "Portuguese"
    assert language_name("de") == "German" and language_name("xx") is None


@pytest.mark.parametrize(
    "eircode", ["D02 X285", "V94 T9PX", "A65 F4E2", "H91 E2K3", "T12 Y2W1"]
)
def test_the_irish_pronunciation_guide_leaves_eircodes_alone(eircode):
    spoken = ", ".join(eircode.replace(" ", ""))
    text = f"That's {eircode}, so {spoken}. Ring 1800 20 50 50."
    assert respell(text) == text


OLD_CLINIC_PROMPT = (
    "You are the calm receptionist for {{initial_context.business_name}}.\n\n"
    "Never give medical advice or diagnose. For anyone in severe pain or an "
    "emergency, tell them to call emergency services or go to A&E, then offer "
    "to take a message for reception.\n\n## Voice rules\n- Speak briefly."
)


def test_an_agent_made_before_the_rules_is_brought_up_to_date():
    updated = with_current_safety_rules(OLD_CLINIC_PROMPT, "clinic")
    assert "then offer to take a message" not in updated
    assert "no message, no booking" in updated
    assert "Please hang up now and dial 112 or 999." in updated
    assert GAS_EMERGENCY_NUMBER in updated
    assert "{{initial_context.agent_languages | fallback:English}}" in updated
    assert "## Addresses" not in updated
    assert updated.endswith("Never say goodbye and leave the line open.")
    # Idempotent: a second run changes nothing.
    assert with_current_safety_rules(updated, "clinic") == updated
    assert "## Addresses" in with_current_safety_rules("Plumber.", "trades")
    # The facts page then offers the languages setting for that agent.
    definition = {"nodes": [{"id": "global", "data": {"prompt": updated}}]}
    assert AGENT_LANGUAGES_KEY in {f.key for f in fact_fields(definition, {})}


def test_a_current_starter_needs_no_update():
    for starter in INBOUND:
        prompt = _global_prompt(starter.definition)
        relabelled = prompt.replace(
            "{{agent_languages |", "{{initial_context.agent_languages |"
        )
        assert with_current_safety_rules(relabelled, starter.category) == relabelled
