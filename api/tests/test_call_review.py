"""The call review: categories per template, the prompt, and checking the
model's answer. Pure functions; no database, no model."""

import json
from datetime import UTC, datetime

import pytest

from api.services.call_review.categories import (
    CLINIC,
    GENERAL,
    REASON_SETS,
    RESTAURANT,
    TEMPLATE_CATEGORY_FACT,
    reason_set,
    starter_marker,
    template_for_workflow,
)
from api.services.call_review.review import (
    MAX_QUESTIONS,
    MAX_TRANSCRIPT_CHARS,
    REQUEST_TAGS_KEY,
    SILENT_SUMMARY,
    ReviewParseError,
    has_caller_speech,
    parse_review,
    purged_review,
    request_tags,
    response_schema,
    silent_review,
    stored_review,
    system_prompt,
    transcript_lines,
    user_prompt,
)

NOW = datetime(2026, 11, 6, 13, 41, tzinfo=UTC)


def _event(kind, text, turn=1, final=True):
    return {
        "type": kind,
        "payload": {"text": text, "final": final},
        "turn": turn,
        "timestamp": "2026-11-06T13:41:00+00:00",
    }


LOGS = {
    "realtime_feedback_events": [
        _event("rtf-bot-text", "Hi, thanks for calling Bia Bistro.", turn=1),
        _event("rtf-bot-text", "How can I help?", turn=1),
        _event("rtf-user-transcription", "Have you a table", turn=1, final=False),
        _event("rtf-user-transcription", "Have you a table for four tonight?", turn=1),
        {"type": "rtf-function-call-start", "payload": {"function_name": "check"}},
        _event("rtf-bot-text", "Yes, 7:00 pm works.", turn=2),
        {"type": "rtf-ttfb-metric", "payload": {"ttfb_seconds": 0.4}},
    ]
}


# --- categories -------------------------------------------------------------


def test_every_set_ends_in_other_and_has_unique_keys():
    for reasons in REASON_SETS.values():
        assert reasons.keys[-1] == "other"
        assert len(set(reasons.keys)) == len(reasons.keys)


def test_restaurant_and_clinic_reasons_as_agreed():
    assert [r.label for r in RESTAURANT.reasons] == [
        "Reservations",
        "Questions (hours, menu, parking)",
        "Changes & cancellations",
        "Takeaway orders",
        "Other",
    ]
    assert [r.label for r in CLINIC.reasons] == [
        "Appointments",
        "Questions",
        "Changes & cancellations",
        "Urgent",
        "Other",
    ]


def test_restaurant_keys_match_the_sample_data():
    # ui/src/lib/sampleData.ts SAMPLE_REASONS
    assert RESTAURANT.keys == (
        "reservations",
        "questions",
        "changes",
        "takeaway",
        "other",
    )


@pytest.mark.parametrize(
    "template, expected",
    [
        ("restaurant", "restaurant"),
        ("telephony", "general"),
        (None, "general"),
        ("x", "general"),
    ],
)
def test_reason_set_falls_back_to_general(template, expected):
    assert reason_set(template).template == expected


def test_unknown_key_is_labelled_other():
    assert RESTAURANT.label("haircut") == "Other"


def _definition(prompt):
    return {"nodes": [{"id": "start", "data": {"prompt": prompt}}]}


MARKERS = [
    ("You take phone bookings for", "restaurant"),
    ("You are the calm, professional phone receptionist for", "clinic"),
]


def test_stored_template_fact_wins():
    definition = _definition("You take phone bookings for Bia Bistro.")
    facts = {TEMPLATE_CATEGORY_FACT: "salon"}
    assert template_for_workflow(definition, facts, MARKERS) == "salon"


def test_template_found_from_its_opening_words():
    definition = _definition(
        "You take phone bookings for Bia Bistro. About the place: ..."
    )
    assert template_for_workflow(definition, {}, MARKERS) == "restaurant"


def test_agent_built_another_way_is_general():
    definition = _definition("You sell solar panels.")
    assert template_for_workflow(definition, None, MARKERS) == "general"
    assert template_for_workflow(None, None, MARKERS) == "general"


def test_starter_marker_is_text_before_the_first_placeholder():
    definition = _definition("You take phone bookings for {{business_name}}. More")
    assert starter_marker(definition) == "You take phone bookings for"
    assert starter_marker(_definition("Hi {{name}}")) is None


def test_every_inbound_starter_maps_to_its_own_category():
    """Each inbound starter's own definition is recognised as that starter
    (real templates; guards against two starters sharing opening words)."""
    from api.services.workflow.starter_templates import STARTER_TEMPLATES

    for starter in STARTER_TEMPLATES:
        if starter.call_type == "inbound":
            assert template_for_workflow(starter.definition, {}) == starter.category, (
                starter.name
            )


# --- transcript and prompt ----------------------------------------------------


def test_transcript_lines_follow_the_chat():
    assert transcript_lines(LOGS) == [
        ("Agent", "Hi, thanks for calling Bia Bistro. How can I help?"),
        ("Caller", "Have you a table for four tonight?"),
        ("Agent", "Yes, 7:00 pm works."),
    ]
    assert transcript_lines({}) == []
    assert transcript_lines(None) == []


def test_caller_speech_comes_from_the_tag():
    assert has_caller_speech({"call_tags": ["end_call", "user_speech"]})
    assert not has_caller_speech({"call_tags": ["user_hangup"]})
    assert not has_caller_speech({})


def test_system_prompt_lists_the_reasons_in_plain_words():
    prompt = system_prompt(RESTAURANT)
    assert "a restaurant" in prompt
    for reason in RESTAURANT.reasons:
        assert f'"{reason.key}": {reason.label}' in prompt
    assert "7:00 pm" in prompt


def test_user_prompt_has_details_and_call_but_no_numbers():
    prompt = user_prompt(
        transcript_lines(LOGS),
        {
            "caller_name": "Declan Murphy",
            "party_size": "4",
            "callback_number": "+353871234567",
        },
    )
    assert "caller name: Declan Murphy" in prompt
    assert "party size: 4" in prompt
    assert "+353871234567" not in prompt
    assert "Caller: Have you a table for four tonight?" in prompt


def test_long_calls_keep_start_and_end():
    lines = [("Caller", "start")] + [("Agent", "x" * 100)] * 200 + [("Caller", "end")]
    prompt = user_prompt(lines, {})
    assert "start" in prompt and "end" in prompt
    assert "middle of the call left out" in prompt
    assert len(prompt) < MAX_TRANSCRIPT_CHARS + 200


def test_schema_limits_reason_to_the_set():
    schema = response_schema(CLINIC)
    assert schema["properties"]["reason"]["enum"] == list(CLINIC.keys)
    assert set(schema["required"]) == {
        "summary",
        "reason",
        "unanswered_questions",
        "time_was_full",
    }


# --- parsing the answer -------------------------------------------------------


def _answer(**overrides):
    data = {
        "summary": "Booked a table for 4 tonight at 7:00 pm.  Asked about parking.",
        "reason": "reservations",
        "unanswered_questions": [],
        "time_was_full": False,
    }
    data.update(overrides)
    return json.dumps(data)


def test_good_answer_becomes_the_stored_review():
    review = parse_review(_answer(), RESTAURANT, model="m", now=NOW)
    assert review == {
        "version": 1,
        "summary": "Booked a table for 4 tonight at 7:00 pm. Asked about parking.",
        "reason": "reservations",
        "reason_label": "Reservations",
        "unanswered_questions": [],
        "time_was_full": False,
        "request_tags": [],
        "model": "m",
        "created_at": NOW.isoformat(),
    }


@pytest.mark.parametrize(
    "text", ["", None, "not json", "[1, 2]", '{"summary": ""}', '{"reason": "other"}']
)
def test_unusable_answers_are_errors(text):
    with pytest.raises(ReviewParseError):
        parse_review(text, RESTAURANT, model="m", now=NOW)


@pytest.mark.parametrize("reason", ["haircut", None, 3, "Reservations "])
def test_unknown_reason_becomes_other(reason):
    review = parse_review(_answer(reason=reason), RESTAURANT, model="m", now=NOW)
    if reason == "Reservations ":
        assert review["reason"] == "reservations"
    else:
        assert review["reason"] == "other"
        assert review["reason_label"] == "Other"


def test_questions_are_cleaned_and_capped():
    questions = [
        "  Do you have gluten-free pasta? ",
        "",
        5,
        "Do you have gluten-free pasta?",
    ]
    questions += [f"Question {i}?" for i in range(5)]
    review = parse_review(
        _answer(unanswered_questions=questions), RESTAURANT, model="m", now=NOW
    )
    assert review["unanswered_questions"][0] == "Do you have gluten-free pasta?"
    assert len(review["unanswered_questions"]) == MAX_QUESTIONS
    assert (
        parse_review(
            _answer(unanswered_questions="a string"), RESTAURANT, model="m", now=NOW
        )["unanswered_questions"]
        == []
    )


@pytest.mark.parametrize(
    "value, expected", [(True, True), ("true", False), (None, False)]
)
def test_time_was_full_only_when_true(value, expected):
    review = parse_review(_answer(time_was_full=value), RESTAURANT, model="m", now=NOW)
    assert review["time_was_full"] is expected


def test_long_summary_is_cut():
    review = parse_review(
        _answer(summary="word " * 200), RESTAURANT, model="m", now=NOW
    )
    assert len(review["summary"]) <= 300
    assert review["summary"].endswith("…")


def test_silent_review_needs_no_model():
    review = silent_review(GENERAL, now=NOW)
    assert review["summary"] == SILENT_SUMMARY
    assert review["reason"] == "other"
    assert review["unanswered_questions"] == []
    assert review["time_was_full"] is False


def test_stored_review_ignores_malformed():
    review = silent_review(GENERAL, now=NOW)
    assert stored_review({"call_review": review}) == review
    assert stored_review({"call_review": "x"}) is None
    assert stored_review({}) is None
    assert stored_review(None) is None


def test_purge_keeps_reason_drops_what_was_said():
    review = parse_review(
        _answer(unanswered_questions=["Gluten-free?"], time_was_full=True),
        RESTAURANT,
        model="m",
        now=NOW,
    )
    kept = purged_review(review)
    assert "summary" not in kept and "unanswered_questions" not in kept
    assert kept["reason"] == "reservations"
    assert kept["time_was_full"] is True
    assert purged_review(None) is None


def test_retention_purge_keeps_only_the_reason_of_a_review():
    from api.db.models import WorkflowRunModel
    from api.db.retention_client import apply_purged_shape

    review = parse_review(
        _answer(unanswered_questions=["Gluten-free?"]), RESTAURANT, model="m", now=NOW
    )
    run = WorkflowRunModel(
        name="call",
        logs={"realtime_feedback_events": []},
        initial_context={},
        gathered_context={},
        extra={},
        annotations={"call_review": review, "follow_up": {"done_at": "x"}},
    )
    apply_purged_shape(run, NOW.isoformat())
    assert run.annotations == {"call_review": purged_review(review)}
    assert "summary" not in run.annotations["call_review"]

    plain = WorkflowRunModel(
        name="call",
        logs={},
        initial_context={},
        gathered_context={},
        extra={},
        annotations={"note": "x"},
    )
    apply_purged_shape(plain, NOW.isoformat())
    assert plain.annotations == {}


# --- special-request tags -------------------------------------------------------


def test_only_restaurants_have_request_tags():
    assert [t.label for t in RESTAURANT.request_tags] == [
        "Allergies & diets",
        "Birthday or celebration",
        "High chair or kids",
        "Accessibility",
        "Seating preference",
        "Other request",
    ]
    assert CLINIC.request_tags == () and GENERAL.request_tags == ()


def test_schema_asks_for_tags_only_where_there_are_some_and_never_requires_them():
    schema = response_schema(RESTAURANT)
    assert schema["properties"]["request_tags"]["items"]["enum"] == list(
        RESTAURANT.request_tag_keys
    )
    assert "request_tags" not in schema["required"]
    assert "request_tags" not in response_schema(CLINIC)["properties"]


def test_prompt_lists_the_tags_for_restaurants_only():
    assert "request_tags" in system_prompt(RESTAURANT)
    assert "Allergies & diets" in system_prompt(RESTAURANT)
    assert "request_tags" not in system_prompt(CLINIC)


def test_tags_are_cleaned_into_the_sets_own_order():
    review = parse_review(
        _answer(request_tags=["seating", "x", "Allergies_Diets", "seating", 4]),
        RESTAURANT,
        model="m",
        now=NOW,
    )
    assert review["request_tags"] == ["allergies_diets", "seating"]


@pytest.mark.parametrize("value", [None, "seating", {"a": 1}])
def test_missing_or_malformed_tags_mean_none(value):
    data = json.loads(_answer())
    if value is not None:
        data["request_tags"] = value
    review = parse_review(json.dumps(data), RESTAURANT, model="m", now=NOW)
    assert review["request_tags"] == []


def test_other_businesses_store_no_tags():
    review = parse_review(
        _answer(reason="appointments", request_tags=["seating"]),
        CLINIC,
        model="m",
        now=NOW,
    )
    assert REQUEST_TAGS_KEY not in review
    assert REQUEST_TAGS_KEY not in silent_review(CLINIC, now=NOW)
    assert silent_review(RESTAURANT, now=NOW)[REQUEST_TAGS_KEY] == []


def test_old_reviews_read_as_not_tagged():
    old = {"version": 1, "reason": "reservations", "summary": "Booked."}
    assert request_tags(old) is None
    assert request_tags(None) is None
    assert request_tags({**old, "request_tags": ["kids"]}) == ["kids"]


def test_purge_drops_the_tags():
    review = parse_review(
        _answer(request_tags=["allergies_diets"]), RESTAURANT, model="m", now=NOW
    )
    assert REQUEST_TAGS_KEY not in purged_review(review)


def test_demo_seed_tags_match_what_was_said():
    """Each seeded restaurant booking is tagged with what the caller asked
    for on the call, and only that."""
    import random

    from api.scripts import demo_businesses as demo

    rng = random.Random(7)
    seen: set[str] = set()
    for _ in range(300):
        ctx = demo.Ctx(
            rng=rng,
            caller=demo.RESTAURANT.callers[0],
            started=datetime(2026, 11, 6, 12, 0),
            business=demo.RESTAURANT,
            greeting="Hello.",
        )
        plan = rng.choice([demo._r_book, demo._r_group])(ctx)
        said = " ".join(step.text for step in plan.steps if step.kind == "caller")
        tags = set(plan.request_tags)
        seen |= tags
        assert tags <= set(RESTAURANT.request_tag_keys)
        assert ("allergies_diets" in tags) == any(
            w in said for w in ("coeliac", "nut allergy", "dairy-free")
        )
        assert ("kids" in tags) == ("high chair" in said)
        assert ("accessibility" in tags) == ("wheelchair" in said)
        assert ("seating" in tags) == ("terrace" in said or "window" in said)
        assert ("celebration" in tags) == any(
            w in said
            for w in ("birthday", "anniversary", "christening", "Christmas party")
        )
    assert seen == {
        "allergies_diets",
        "celebration",
        "kids",
        "accessibility",
        "seating",
    }
