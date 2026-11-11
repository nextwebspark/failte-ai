"""Every agent is told today's date, in the business's timezone."""

from datetime import UTC, datetime

from api.services.workflow.call_date import call_timezone, todays_date_line
from api.services.workflow.pipecat_engine_context_composer import (
    compose_system_prompt_for_node,
)

NOV_6_LATE = datetime(2026, 11, 6, 23, 30, tzinfo=UTC)


def test_line_names_weekday_date_year_and_time_in_ireland_by_default():
    line = todays_date_line({}, now=datetime(2026, 11, 6, 14, 5, tzinfo=UTC))
    assert line.startswith(
        "Today is Friday 6 November 2026 and it's 14:05 (Europe/Dublin time)."
    )
    assert "never a date in the past" in line


def test_summer_time_is_applied():
    line = todays_date_line({}, now=datetime(2026, 7, 3, 12, 0, tzinfo=UTC))
    assert "Friday 3 July 2026 and it's 13:00" in line


def test_business_timezone_can_move_the_date():
    # 23:30 in Dublin is already Saturday morning in Tokyo.
    assert "Friday 6 November" in todays_date_line({}, now=NOV_6_LATE)
    tokyo = todays_date_line({"timezone": "Asia/Tokyo"}, now=NOV_6_LATE)
    assert "Saturday 7 November 2026" in tokyo and "(Asia/Tokyo time)" in tokyo


def test_unknown_or_blank_timezone_falls_back_to_ireland():
    for bad in ("Mars/Olympus", "", "   ", None, 42, "../etc"):
        assert call_timezone({"timezone": bad}).key == "Europe/Dublin"
    assert call_timezone(None).key == "Europe/Dublin"


class _Node:
    def __init__(self, prompt: str, add_global_prompt: bool = True):
        self.prompt = prompt
        self.add_global_prompt = add_global_prompt


class _Graph:
    def __init__(self, global_prompt: str | None):
        self.global_node_id = "g" if global_prompt is not None else None
        self.nodes = {"g": _Node(global_prompt or "")}


def test_date_line_comes_first_in_the_composed_prompt():
    composed = compose_system_prompt_for_node(
        node=_Node("Take the booking."),
        workflow=_Graph("You are the receptionist."),
        format_prompt=lambda s: s,
        has_recordings=False,
        todays_date="Today is Friday.",
    )
    assert composed.text == (
        "Today is Friday.\n\nYou are the receptionist.\n\nTake the booking."
    )


def test_composer_without_a_date_is_unchanged():
    composed = compose_system_prompt_for_node(
        node=_Node("Take the booking."),
        workflow=_Graph(None),
        format_prompt=lambda s: s,
        has_recordings=False,
    )
    assert composed.text == "Take the booking."
