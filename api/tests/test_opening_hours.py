"""Structured opening hours: validation, the generated sentence, open/closed
at a moment (time zones, daylight saving, ranges past midnight), the
transfer gate, the owner's save and the after-hours count. Pure."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pipecat.utils.enums import RealtimeFeedbackType
from pydantic import ValidationError

from api.schemas.opening_hours import OpeningHours, OpenRange
from api.services.call_notifications.outcome import transfer_failed
from api.services.workflow.business_facts import BusinessFactsError
from api.services.workflow.opening_hours import (
    SCHEDULE_KEY,
    TEXT_KEY,
    after_hours_count,
    closed_transfer_result,
    describe_opening_hours,
    is_open,
    minute_ranges,
    open_minutes,
    opening_hours_facts,
    opening_hours_updates,
    parse_opening_hours,
    stored_opening_hours,
    transfer_closed,
)

DUBLIN = ZoneInfo("Europe/Dublin")
FUNCTION_CALL_END = RealtimeFeedbackType.FUNCTION_CALL_END


def week(*days, **kwargs) -> OpeningHours:
    return OpeningHours(
        days=tuple(tuple(OpenRange(open=o, close=c) for o, c in day) for day in days),
        **kwargs,
    )


LUNCH_DINNER = (("12:00", "15:00"), ("17:00", "22:00"))
RESTAURANT = week((), *[LUNCH_DINNER] * 6)


def dublin(*args) -> datetime:
    return datetime(*args, tzinfo=DUBLIN)


# ------------------------------------------------------------- validation


def test_defaults_to_dublin_and_transfers_only_when_open():
    assert RESTAURANT.timezone == "Europe/Dublin"
    assert RESTAURANT.transfer_only_when_open is True


@pytest.mark.parametrize("bad", ["9:00", "24:00", "12:60", "noon", ""])
def test_rejects_times_that_are_not_hh_mm(bad):
    with pytest.raises(ValidationError):
        OpenRange(open=bad, close="17:00")


def test_rejects_unknown_zone():
    with pytest.raises(ValidationError):
        week(*[()] * 7, timezone="Mars/Olympus")


def test_needs_seven_days():
    with pytest.raises(ValidationError):
        OpeningHours(days=((),) * 6)


@pytest.mark.parametrize(
    "ranges",
    [
        (("12:00", "15:00"), ("14:00", "18:00")),  # overlap
        (("17:00", "22:00"), ("12:00", "15:00")),  # out of order
        (("12:00", "15:00"), ("15:00", "18:00")),  # touching: one range
        (("18:00", "02:00"), ("03:00", "05:00")),  # past midnight, not last
        (("08:00", "09:00"),) * 5,  # too many
    ],
)
def test_rejects_bad_day(ranges):
    with pytest.raises(ValidationError):
        week(ranges, *[()] * 6)


def test_note_is_one_plain_line():
    hours = week(*[()] * 7, note="  Closed on\n bank {{holidays}} ")
    assert hours.note == "Closed on bank {holidays}"
    assert week(*[()] * 7, note="   ").note is None


# ------------------------------------------------------------------ words


def test_describes_the_example():
    assert (
        describe_opening_hours(RESTAURANT)
        == "Tuesday to Sunday 12 to 3 pm and 5 to 10 pm, closed Monday"
    )


def test_describes_mixed_week_with_minutes_and_note():
    hours = week(
        *[(("08:30", "18:00"),)] * 4,
        (("08:30", "16:00"),),
        (("09:00", "13:00"),),
        (),
        note="closed on bank holidays.",
    )
    assert describe_opening_hours(hours) == (
        "Monday to Thursday 8:30 am to 6 pm, Friday 8:30 am to 4 pm, "
        "Saturday 9 am to 1 pm, closed Sunday. Closed on bank holidays."
    )


def test_describes_every_day_midnight_and_overnight():
    assert describe_opening_hours(week(*[(("00:00", "00:00"),)] * 7)) == (
        "Every day open 24 hours"
    )
    assert describe_opening_hours(week(*[(("17:00", "00:00"),)] * 7)) == (
        "Every day 5 pm to midnight"
    )
    late = week(*[()] * 4, (("18:00", "02:00"),), (("18:00", "02:00"),), ())
    assert describe_opening_hours(late) == (
        "Friday and Saturday 6 pm to 2 am, closed Monday to Thursday and Sunday"
    )


def test_same_hours_on_days_apart_are_said_together():
    nine_five = (("09:00", "17:00"),)
    hours = week(nine_five, (), nine_five, nine_five, nine_five, (), ())
    assert describe_opening_hours(hours) == (
        "Monday and Wednesday to Friday 9 am to 5 pm, closed Tuesday, Saturday and Sunday"
    )


def test_closed_all_week():
    assert describe_opening_hours(week(*[()] * 7)) == "Closed every day"


def test_noon_and_morning_ranges():
    hours = week(*[(("11:00", "15:00"), ("19:00", "23:30"))] * 7)
    assert describe_opening_hours(hours) == (
        "Every day 11 am to 3 pm and 7 to 11:30 pm"
    )


# ------------------------------------------------------------------ times


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (dublin(2026, 11, 10, 11, 59), False),  # Tuesday before lunch
        (dublin(2026, 11, 10, 12, 0), True),  # opening minute
        (dublin(2026, 11, 10, 14, 59), True),
        (dublin(2026, 11, 10, 15, 0), False),  # closing minute: closed
        (dublin(2026, 11, 10, 16, 30), False),  # between lunch and dinner
        (dublin(2026, 11, 10, 21, 30), True),
        (dublin(2026, 11, 9, 13, 0), False),  # Monday: closed
    ],
)
def test_is_open_split_day(moment, expected):
    assert is_open(RESTAURANT, moment) is expected


def test_is_open_reads_the_business_zone_not_utc():
    # 12:30 in Dublin summer time is 11:30 UTC.
    assert is_open(RESTAURANT, datetime(2026, 7, 7, 11, 30, tzinfo=UTC))
    # 11:30 UTC in winter is 11:30 in Dublin: not open yet.
    assert not is_open(RESTAURANT, datetime(2026, 11, 10, 11, 30, tzinfo=UTC))
    # A naive time is UTC.
    assert is_open(RESTAURANT, datetime(2026, 7, 7, 11, 30))


def test_is_open_in_another_zone():
    ny = week(*[(("09:00", "17:00"),)] * 7, timezone="America/New_York")
    # 14:00 UTC is 09:00 in New York (EST, winter).
    assert is_open(ny, datetime(2026, 11, 10, 14, 0, tzinfo=UTC))
    assert not is_open(ny, datetime(2026, 11, 10, 13, 59, tzinfo=UTC))


def test_daylight_saving_keeps_wall_clock_times():
    nine_five = week(*[(("09:00", "17:00"),)] * 7)
    # Clocks went forward on Sunday 29 March 2026 (01:00 UTC).
    assert is_open(nine_five, datetime(2026, 3, 29, 8, 0, tzinfo=UTC))  # 09:00 IST
    assert not is_open(nine_five, datetime(2026, 3, 28, 8, 0, tzinfo=UTC))  # 08:00 GMT
    # Clocks went back on Sunday 25 October 2026 (01:00 UTC).
    assert not is_open(
        nine_five, datetime(2026, 10, 24, 16, 0, tzinfo=UTC)
    )  # 17:00 IST
    assert is_open(nine_five, datetime(2026, 10, 25, 16, 0, tzinfo=UTC))  # 16:00 GMT


def test_repeated_hour_at_fall_back_is_read_on_the_wall_clock():
    early = week(*[(("00:30", "01:30"),)] * 7)
    # 01:15 happens twice on 25 October 2026 in Dublin: both are open.
    assert is_open(early, datetime(2026, 10, 25, 0, 15, tzinfo=UTC))  # 01:15 IST
    assert is_open(early, datetime(2026, 10, 25, 1, 15, tzinfo=UTC))  # 01:15 GMT
    assert not is_open(early, datetime(2026, 10, 25, 1, 45, tzinfo=UTC))  # 01:45 GMT


def test_range_past_midnight_runs_into_the_next_day():
    # Open Friday and Saturday 18:00-02:00 only.
    late = week(*[()] * 4, (("18:00", "02:00"),), (("18:00", "02:00"),), ())
    assert is_open(late, dublin(2026, 11, 13, 23, 0))  # Friday night
    assert is_open(late, dublin(2026, 11, 14, 1, 59))  # Saturday early: Friday's
    assert not is_open(late, dublin(2026, 11, 14, 2, 0))
    assert is_open(late, dublin(2026, 11, 15, 0, 30))  # Sunday early: Saturday's
    assert not is_open(
        late, dublin(2026, 11, 13, 1, 0)
    )  # Friday early: Thursday closed


def test_sunday_overnight_wraps_into_monday():
    sunday = week(*[()] * 6, (("20:00", "03:00"),))
    assert is_open(sunday, dublin(2026, 11, 16, 2, 0))  # Monday 02:00
    assert not is_open(sunday, dublin(2026, 11, 16, 3, 0))


def test_until_midnight_and_all_day():
    evening = week(*[(("17:00", "00:00"),)] * 7)
    assert is_open(evening, dublin(2026, 11, 10, 23, 59))
    assert not is_open(evening, dublin(2026, 11, 11, 0, 0))
    always = week(*[(("00:00", "00:00"),)] * 7)
    assert is_open(always, dublin(2026, 11, 10, 0, 0))
    assert is_open(always, dublin(2026, 11, 10, 23, 59))


# ---------------------------------------------------------------- storage


def test_stored_round_trip_and_unreadable_values():
    facts = opening_hours_facts(RESTAURANT)
    assert facts[TEXT_KEY] == describe_opening_hours(RESTAURANT)
    assert facts["timezone"] == "Europe/Dublin"
    assert stored_opening_hours(facts) == RESTAURANT
    assert parse_opening_hours(json.loads(facts[SCHEDULE_KEY])) == RESTAURANT
    assert stored_opening_hours({}) is None
    assert stored_opening_hours(None) is None
    assert stored_opening_hours({SCHEDULE_KEY: "not json"}) is None
    assert stored_opening_hours({SCHEDULE_KEY: '{"days": []}'}) is None


def test_clearing_keeps_the_sentence():
    assert opening_hours_facts(None) == {SCHEDULE_KEY: None}


# ------------------------------------------------------------- transfer gate


def test_gate_without_structured_hours_always_tries():
    assert transfer_closed({}, dublin(2026, 11, 9, 3, 0)) is False
    assert (
        transfer_closed({TEXT_KEY: "Closed Mondays"}, dublin(2026, 11, 9, 3, 0))
        is False
    )
    assert transfer_closed(None) is False


def test_gate_closed_and_open():
    facts = opening_hours_facts(RESTAURANT)
    assert transfer_closed(facts, dublin(2026, 11, 9, 13, 0)) is True  # Monday
    assert transfer_closed(facts, dublin(2026, 11, 10, 13, 0)) is False


def test_gate_respects_the_owner_switch():
    facts = opening_hours_facts(
        RESTAURANT.model_copy(update={"transfer_only_when_open": False})
    )
    assert transfer_closed(facts, dublin(2026, 11, 9, 13, 0)) is False


def test_closed_result_is_not_a_transfer_nobody_answered():
    result = closed_transfer_result()
    assert result["action"] == "transfer_failed"
    assert result["reason"] == "closed"
    # As _handle_transfer_result stores it in the call log.
    stored = {"status": "transfer_failed", "reason": "closed", "message": "x"}
    logs = {
        "realtime_feedback_events": [
            {"type": FUNCTION_CALL_END.value, "payload": {"result": str(stored)}}
        ]
    }
    assert transfer_failed(logs) is False
    unanswered = {**stored, "reason": "timeout"}
    logs["realtime_feedback_events"][0]["payload"]["result"] = str(unanswered)
    assert transfer_failed(logs) is True


# ------------------------------------------------------------- owner's save


def test_save_sets_times_and_sentence_dropping_a_text_edit():
    updates = opening_hours_updates(
        {},
        {TEXT_KEY: "whatever", "address": "Quay St"},
        has_hours_fact=True,
        hours_sent=True,
        hours=RESTAURANT,
    )
    assert updates["address"] == "Quay St"
    assert updates[TEXT_KEY] == describe_opening_hours(RESTAURANT)
    assert stored_opening_hours(updates) == RESTAURANT


def test_save_refuses_times_for_an_agent_without_hours():
    with pytest.raises(BusinessFactsError):
        opening_hours_updates(
            {}, {}, has_hours_fact=False, hours_sent=True, hours=RESTAURANT
        )


def test_text_edit_refused_while_times_are_set():
    facts = opening_hours_facts(RESTAURANT)
    with pytest.raises(BusinessFactsError):
        opening_hours_updates(
            facts,
            {TEXT_KEY: "Open late"},
            has_hours_fact=True,
            hours_sent=False,
            hours=None,
        )
    # The same text (an unchanged form field) is fine and changes nothing.
    assert (
        opening_hours_updates(
            facts,
            {TEXT_KEY: facts[TEXT_KEY]},
            has_hours_fact=True,
            hours_sent=False,
            hours=None,
        )
        == {}
    )


def test_free_text_agent_keeps_editing_text():
    assert opening_hours_updates(
        {TEXT_KEY: "Mon-Fri 9-5"},
        {TEXT_KEY: "Mon-Sat 9-5"},
        has_hours_fact=True,
        hours_sent=False,
        hours=None,
    ) == {TEXT_KEY: "Mon-Sat 9-5"}


def test_clearing_times_with_new_text():
    facts = opening_hours_facts(RESTAURANT)
    assert opening_hours_updates(
        facts,
        {TEXT_KEY: "By appointment"},
        has_hours_fact=True,
        hours_sent=True,
        hours=None,
    ) == {TEXT_KEY: "By appointment", SCHEDULE_KEY: None}


# --------------------------------------------------------------- after hours


def test_after_hours_count_skips_agents_without_hours():
    calls = [
        (1, datetime(2026, 11, 9, 13, 0, tzinfo=UTC)),  # Monday: closed
        (1, datetime(2026, 11, 10, 13, 0, tzinfo=UTC)),  # open
        (1, datetime(2026, 11, 10, 16, 0, tzinfo=UTC)),  # between services
        (2, datetime(2026, 11, 9, 13, 0, tzinfo=UTC)),  # agent 2: no hours
    ]
    assert after_hours_count(calls, {1: RESTAURANT}) == 2
    assert after_hours_count(calls, {}) == 0


def _call(run_id: int, workflow_id: int, at: datetime):
    from api.services.dashboard.calls import CallResult, CallView

    return CallView(
        run_id=run_id,
        workflow_id=workflow_id,
        workflow_name="",
        created_at=at,
        result=CallResult.HANDLED,
        duration_seconds=60,
        has_recording=False,
        caller_number=None,
        caller_name=None,
        call_reason=None,
        callback_number=None,
        follow_up_mark=None,
    )


def test_dashboard_after_hours_names_agents_left_out():
    from api.services.dashboard.summary import after_hours

    agents = [
        {
            "id": 1,
            "name": "Restaurant",
            "status": "active",
            "opening_hours_schedule": opening_hours_facts(RESTAURANT)[SCHEDULE_KEY],
        },
        {"id": 2, "name": "Free text", "status": "active"},
        {"id": 3, "name": "Archived, no calls", "status": "archived"},
        {"id": 4, "name": "Archived, called", "status": "archived"},
    ]
    calls = [
        _call(1, 1, datetime(2026, 11, 9, 13, 0, tzinfo=UTC)),
        _call(2, 1, datetime(2026, 11, 10, 13, 0, tzinfo=UTC)),
        _call(3, 2, datetime(2026, 11, 9, 13, 0, tzinfo=UTC)),
        _call(4, 4, datetime(2026, 11, 9, 13, 0, tzinfo=UTC)),
    ]
    result = after_hours(calls, agents)
    assert result["calls"] == 1
    assert result["agents_without_hours"] == [
        {"id": 2, "name": "Free text"},
        {"id": 4, "name": "Archived, called"},
    ]
    assert [c["run_id"] for c in result["recent"]] == [1]
    assert after_hours(calls, agents[1:])["calls"] is None


def test_after_hours_lists_the_newest_five_with_who_and_how():
    from api.services.dashboard.summary import after_hours

    agents = [
        {
            "id": 1,
            "name": "Restaurant",
            "status": "active",
            "opening_hours_schedule": opening_hours_facts(RESTAURANT)[SCHEDULE_KEY],
        }
    ]
    monday = datetime(2026, 11, 9, 10, 0, tzinfo=UTC)  # closed all day
    # Newest first, as Home loads them; one open-hours call in between.
    calls = [_call(i, 1, monday - timedelta(minutes=i)) for i in range(1, 8)]
    calls.insert(2, _call(99, 1, datetime(2026, 11, 10, 13, 0, tzinfo=UTC)))
    result = after_hours(calls, agents)
    assert result["calls"] == 7
    assert [c["run_id"] for c in result["recent"]] == [1, 2, 3, 4, 5]
    first = result["recent"][0]
    assert set(first) == {
        "run_id",
        "workflow_id",
        "created_at",
        "caller_number",
        "caller_name",
        "result",
    }
    assert (
        after_hours(calls, [{**agents[0], "opening_hours_schedule": None}])["recent"]
        == []
    )


# ------------------------------------------------------------ the open band


def test_open_minutes_include_last_nights_late_range():
    late = week(*[()] * 5, (("18:00", "02:00"),), ())
    saturday = open_minutes(late, date(2026, 11, 7), DUBLIN)
    sunday = open_minutes(late, date(2026, 11, 8), DUBLIN)
    assert minute_ranges(saturday) == [(1080, 1440)]
    assert minute_ranges(sunday) == [(0, 120)]


def test_open_minutes_in_another_zone_follow_the_business_clock():
    weekdays = week(*[(("09:00", "17:00"),)] * 5, (), ())
    # Paris is an hour ahead of Dublin in winter.
    paris = open_minutes(weekdays, date(2026, 11, 9), ZoneInfo("Europe/Paris"))
    assert minute_ranges(paris) == [(600, 1080)]


def test_minute_ranges():
    assert minute_ranges([False, True, True, False, True]) == [(1, 3), (4, 5)]
    assert minute_ranges([False] * 3) == []
