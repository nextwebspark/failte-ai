"""Home's numbers: how each call is read, and the tiles, hours, change,
agent status and credit built from them. Pure functions; no database."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from api.services.dashboard.calls import CallResult, call_result, call_view
from api.services.dashboard.summary import (
    DashboardRange,
    NotAnsweringReason,
    agent_status,
    call_change,
    callers_wanted,
    calls_by_hour,
    credit_summary,
    range_bounds,
    recent_calls,
    tiles,
)

NOW = datetime(2026, 11, 6, 15, 0, tzinfo=UTC)
DUBLIN = ZoneInfo("Europe/Dublin")

TRANSFER_FAILED_LOG = {
    "realtime_feedback_events": [
        {
            "type": "rtf-function-call-end",
            "payload": {
                "result": "{'status': 'transfer_failed', 'reason': 'no-answer'}"
            },
        }
    ]
}


def _row(
    run_id=1,
    *,
    minutes_ago=30,
    completed=True,
    gathered=None,
    seconds=60,
    caller="+353871234567",
    hint=False,
    recording=True,
    mark=None,
    review=None,
):
    annotations = {"follow_up": mark} if mark else {}
    if review:
        annotations["call_review"] = review
    return {
        "id": run_id,
        "workflow_id": 14,
        "workflow_name": "Bia Bistro bookings",
        "created_at": NOW - timedelta(minutes=minutes_ago),
        "is_completed": completed,
        "has_recording": recording,
        "gathered_context": gathered
        if gathered is not None
        else {"call_tags": ["user_speech"], "call_status": "user_hangup"},
        "usage_info": {"call_duration_seconds": seconds},
        "initial_context": {"caller_number": caller, "called_number": "+35315550142"},
        "annotations": annotations,
        "transfer_hint": hint,
    }


def _result(gathered, *, logs=None, completed=True, minutes_ago=30, seconds=60):
    return call_result(
        is_completed=completed,
        created_at=NOW - timedelta(minutes=minutes_ago),
        gathered_context=gathered,
        usage_info={"call_duration_seconds": seconds},
        logs=logs,
        now=NOW,
    )


SPOKE = {"call_tags": ["user_speech"], "call_status": "completed"}


@pytest.mark.parametrize(
    ("gathered", "logs", "expected"),
    [
        (SPOKE, None, CallResult.HANDLED),
        ({**SPOKE, "call_status": "transfer_call"}, None, CallResult.PASSED_TO_TEAM),
        ({**SPOKE, "call_status": "call_transferred"}, None, CallResult.PASSED_TO_TEAM),
        ({**SPOKE, "mapped_call_disposition": "XFER"}, None, CallResult.PASSED_TO_TEAM),
        (
            {**SPOKE, "mapped_call_disposition": "callback_requested"},
            None,
            CallResult.CALLBACK_REQUESTED,
        ),
        (
            {**SPOKE, "callback_number": "0871234567"},
            None,
            CallResult.CALLBACK_REQUESTED,
        ),
        (
            {**SPOKE, "booking_outcome": "requested"},
            None,
            CallResult.CALLBACK_REQUESTED,
        ),
        (SPOKE, TRANSFER_FAILED_LOG, CallResult.TRANSFER_NOT_ANSWERED),
        # Nobody picked up, then the agent took their number: still a transfer
        # nobody answered.
        (
            {**SPOKE, "callback_number": "0871234567"},
            TRANSFER_FAILED_LOG,
            CallResult.TRANSFER_NOT_ANSWERED,
        ),
        (
            {"call_tags": [], "call_status": "user_hangup"},
            None,
            CallResult.HUNG_UP_SILENT,
        ),
        ({"call_status": "user_hangup"}, None, CallResult.HUNG_UP_SILENT),
        ({"call_status": "no-answer"}, None, CallResult.NOT_CONNECTED),
        ({**SPOKE, "call_status": "pipeline_error"}, None, CallResult.CALL_DROPPED),
    ],
)
def test_call_result(gathered, logs, expected):
    assert _result(gathered, logs=logs) == expected


@pytest.mark.parametrize(
    "extra",
    [
        {"caller_name": "Niamh Kelly"},
        {"call_reason": "Asked if dogs are allowed on the terrace"},
        {"callback_number": ""},
        # The agent says it booked but no calendar confirmed it: not a
        # follow-up, and never counted as a booking made.
        {"caller_name": "Paul Kennedy", "booking_outcome": "booked"},
    ],
)
def test_details_written_down_on_ordinary_calls_are_not_a_callback(extra):
    assert _result({**SPOKE, **extra}) == CallResult.HANDLED


def test_spoke_then_hung_up_quickly_is_early_not_handled():
    gathered = {"call_tags": ["user_speech"], "call_status": "user_hangup"}
    assert _result(gathered, seconds=6) == CallResult.HUNG_UP_EARLY
    assert _result(gathered, seconds=90) == CallResult.HANDLED


def test_calendar_booking_counts_as_booking_made():
    gathered = {
        **SPOKE,
        "tool_results": [
            {
                "status": "completed",
                "function_name": "book_appointment",
                "arguments": {"slot_id": "2026-11-07T19:00:00+00:00"},
                "result": {
                    "booked": True,
                    "event_id": "e1",
                    "starts_at": "2026-11-07T19:00:00+00:00",
                },
            }
        ],
    }
    assert _result(gathered) == CallResult.BOOKING_MADE


def test_unfinished_call_is_in_progress_only_for_a_while():
    assert _result({}, completed=False, minutes_ago=5) == CallResult.IN_PROGRESS
    assert _result({}, completed=False, minutes_ago=300) == CallResult.HUNG_UP_SILENT


def test_call_view_reads_caller_and_mark():
    view = call_view(
        _row(
            gathered={
                **SPOKE,
                "caller_name": " Sinéad ",
                "call_reason": "Change booking",
            },
            mark={"done_at": NOW.isoformat(), "done_by": "Maria"},
        ),
        None,
        NOW,
    )
    assert view.caller_name == "Sinéad"
    assert view.call_reason == "Change booking"
    assert view.caller_number == "+353871234567"
    assert view.follow_up_mark["done_by"] == "Maria"
    assert call_view(_row(caller="anonymous"), None, NOW).caller_number is None


def _views(*rows):
    return [
        call_view(r, TRANSFER_FAILED_LOG if r["transfer_hint"] else None, NOW)
        for r in rows
    ]


def test_tiles_count_each_call_once():
    calls = _views(
        _row(1, seconds=120),  # handled
        _row(2, seconds=60),  # handled
        _row(3, gathered={**SPOKE, "call_status": "transfer_call"}, seconds=200),
        _row(4, hint=True, seconds=40),  # transfer not answered
        _row(5, gathered={"call_status": "user_hangup"}, seconds=3),  # silent
        _row(6, gathered={**SPOKE, "callback_number": "087"}, seconds=80),  # callback
        _row(7, completed=False, minutes_ago=1, seconds=0),  # in progress
    )
    result = tiles(calls)
    assert result["calls"] == 7
    assert result["handled"] == 2
    assert result["handled_percent"] == 29
    assert result["passed_to_team"] == 2
    assert result["transfer_picked_up"] == 1
    assert result["transfer_not_answered"] == 1
    assert result["hung_up_silent"] == 1
    assert result["callbacks_requested"] == 1
    assert result["in_progress"] == 1
    assert result["no_conversation"] == 1
    # The tiles add up: every call is in exactly one group.
    assert (
        result["handled"]
        + result["callbacks_requested"]
        + result["passed_to_team"]
        + result["no_conversation"]
        + result["lines_busy"]
        + result["in_progress"]
        == result["calls"]
    )
    # The call in progress and zero lengths are left out of the average.
    assert result["average_call_seconds"] == round((120 + 60 + 200 + 40 + 3 + 80) / 6)


def test_tiles_with_no_calls():
    result = tiles([])
    assert result["calls"] == 0
    assert result["handled_percent"] is None
    assert result["average_call_seconds"] is None


def test_calls_by_hour_uses_local_time():
    # 15:00 UTC on 6 November is 15:00 in Dublin (winter time); in New York 10:00.
    calls = _views(
        _row(1, minutes_ago=0), _row(2, minutes_ago=5), _row(3, minutes_ago=10)
    )
    hours = calls_by_hour(calls, DUBLIN)
    assert hours[15] == 1 and hours[14] == 2 and sum(hours) == 3
    assert calls_by_hour(calls, ZoneInfo("America/New_York"))[10] == 1


def test_recent_calls_are_the_newest_five():
    calls = _views(*[_row(i, minutes_ago=i) for i in range(1, 8)])
    recent = recent_calls(calls)
    assert [c["run_id"] for c in recent] == [1, 2, 3, 4, 5]
    assert recent[0]["result"] == CallResult.HANDLED


def test_range_bounds_today_compares_same_hours_last_week():
    bounds = range_bounds(DashboardRange.TODAY, DUBLIN, NOW)
    assert bounds.start == datetime(2026, 11, 6, 0, 0, tzinfo=DUBLIN)
    assert bounds.end == NOW
    assert bounds.previous_start == datetime(2026, 10, 30, 0, 0, tzinfo=DUBLIN)
    assert bounds.previous_end == NOW - timedelta(days=7)


@pytest.mark.parametrize(
    ("range_", "days"),
    [(DashboardRange.LAST_7_DAYS, 7), (DashboardRange.LAST_30_DAYS, 30)],
)
def test_range_bounds_days_include_today(range_, days):
    bounds = range_bounds(range_, DUBLIN, NOW)
    assert bounds.start.date() == NOW.date() - timedelta(days=days - 1)
    assert bounds.previous_end == bounds.start
    assert bounds.previous_start.date() == NOW.date() - timedelta(days=2 * days - 1)


def test_range_bounds_local_midnight_differs_from_utc():
    # 23:30 UTC on 6 November is already 7 November in Sydney.
    late = datetime(2026, 11, 6, 23, 30, tzinfo=UTC)
    sydney = ZoneInfo("Australia/Sydney")
    assert range_bounds(DashboardRange.TODAY, sydney, late).start == datetime(
        2026, 11, 7, 0, 0, tzinfo=sydney
    )


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [(46, 38, 8), (3, 1, None), (4, 4, None), (5, 0, 5), (0, 7, -7)],
)
def test_call_change_hidden_when_tiny(current, previous, expected):
    assert call_change(current, previous) == expected


AGENTS = [
    {"id": 14, "name": "Bia Bistro", "status": "active"},
    {"id": 15, "name": "Old agent", "status": "archived"},
]


def _number(address="+35315550142", workflow=14, active=True, config_inactive=False):
    return {
        "id": 1,
        "address": address,
        "is_active": active,
        "config_inactive": config_inactive,
        "inbound_workflow_id": workflow,
    }


def _status(numbers, *, workflow_id=None, agents=AGENTS, credit_too_low=False):
    return agent_status(
        agents=agents,
        numbers=numbers,
        workflow_id=workflow_id,
        credit_too_low=credit_too_low,
        last_call_at=None,
    )


def test_agent_answering():
    status = _status([_number()])
    assert status["answering"] is True
    assert status["reason"] is None
    assert status["phone_numbers"] == ["+35315550142"]


@pytest.mark.parametrize(
    ("numbers", "kwargs", "reason"),
    [
        ([], {}, NotAnsweringReason.NO_NUMBER),
        ([_number(workflow=None)], {}, NotAnsweringReason.NO_NUMBER),
        ([_number(active=False)], {}, NotAnsweringReason.NUMBER_OFF),
        ([_number(config_inactive=True)], {}, NotAnsweringReason.NUMBER_OFF),
        ([_number(workflow=15)], {"workflow_id": 15}, NotAnsweringReason.AGENT_OFF),
        ([_number()], {"credit_too_low": True}, NotAnsweringReason.NO_CREDIT),
        ([_number()], {"agents": []}, NotAnsweringReason.NO_AGENT),
        # Filtered to an agent the number doesn't ring.
        ([_number()], {"workflow_id": 15}, NotAnsweringReason.NO_NUMBER),
    ],
)
def test_agent_not_answering(numbers, kwargs, reason):
    status = _status(numbers, **kwargs)
    assert status["answering"] is False
    assert status["reason"] == reason


def test_credit_minutes_use_the_rate():
    credit = credit_summary(
        balance_eur=Decimal("14.20"),
        credit_limit_eur=Decimal("0"),
        rate_per_minute_eur=Decimal("0.12"),
        min_balance_for_call_eur=Decimal("0.50"),
        low_balance_warning_eur=Decimal("5.00"),
    )
    assert credit["minutes_left"] == 118
    assert credit["too_low"] is False and credit["running_low"] is False


def test_credit_too_low_under_the_minimum():
    credit = credit_summary(
        balance_eur=Decimal("0.40"),
        credit_limit_eur=Decimal("0"),
        rate_per_minute_eur=Decimal("0.12"),
        min_balance_for_call_eur=Decimal("0.50"),
        low_balance_warning_eur=Decimal("5.00"),
    )
    assert credit["too_low"] is True and credit["running_low"] is True
    assert credit["minutes_left"] == 3


def _reason(key, label):
    return {"summary": f"{label}.", "reason": key, "reason_label": label}


def test_callers_wanted_counts_reviews_most_common_first():
    calls = _views(
        _row(1, review=_reason("questions", "Questions")),
        _row(2, review=_reason("reservations", "Reservations")),
        _row(3, review=_reason("other", "Other")),
        _row(4, review=_reason("reservations", "Reservations")),
        _row(5),  # finished, not reviewed yet
        _row(6, completed=False, minutes_ago=1),  # on the line: never counted
        _row(7, gathered={"call_status": "no-answer"}),  # never connected
    )
    assert callers_wanted(calls) == [
        {"key": "reservations", "label": "Reservations", "count": 2, "percent": 40},
        {"key": "questions", "label": "Questions", "count": 1, "percent": 20},
        {"key": "other", "label": "Other", "count": 1, "percent": 20},
        {"key": "not_reviewed", "label": "Not reviewed yet", "count": 1, "percent": 20},
    ]


def test_callers_wanted_without_unreviewed_calls_invents_nothing():
    calls = _views(
        *[_row(i, review=_reason("questions", "Questions")) for i in range(3)]
    )
    assert callers_wanted(calls) == [
        {"key": "questions", "label": "Questions", "count": 3, "percent": 100}
    ]
    assert callers_wanted([]) == []


def test_callers_wanted_equal_counts_show_equal_percents():
    calls = _views(
        _row(1, review=_reason("a", "A")),
        _row(2, review=_reason("b", "B")),
        _row(3, review=_reason("c", "C")),
    )
    assert [r["percent"] for r in callers_wanted(calls)] == [33, 33, 33]


def test_recent_calls_carry_the_summary():
    calls = _views(_row(1, review=_reason("reservations", "Reservations")), _row(2))
    recent = recent_calls(calls)
    assert recent[0]["summary"] == "Reservations."
    assert recent[0]["reason_label"] == "Reservations"
    assert recent[1]["summary"] is None


def test_bookings_taken_counts_calendar_bookings():
    assert tiles([])["bookings_taken"] == 0


# ------------------------------------------------- open hours behind the chart


def _agent(agent_id, days, status="active", tz="Europe/Dublin"):
    import json

    schedule = (
        None
        if days is None
        else json.dumps(
            {
                "days": [[{"open": o, "close": c} for o, c in day] for day in days],
                "timezone": tz,
            }
        )
    )
    return {
        "id": agent_id,
        "name": f"Agent {agent_id}",
        "status": status,
        "opening_hours_schedule": schedule,
    }


_NINE_TO_530 = [("09:00", "17:30")]
_WEEKDAYS = [_NINE_TO_530] * 5 + [[], []]
_DUBLIN = ZoneInfo("Europe/Dublin")


def _band(agents, range_, now):
    from api.services.dashboard.summary import opening_hours_band

    bounds = range_bounds(range_, _DUBLIN, now)
    return opening_hours_band([], agents, _DUBLIN, bounds.start, bounds.end)


# Monday 9 November 2026, 3 pm in Dublin.
_MONDAY = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)


def test_band_today_is_todays_hours():
    band = _band([_agent(1, _WEEKDAYS)], DashboardRange.TODAY, _MONDAY)
    assert band["kind"] == "same"
    assert band["ranges"] == [{"start": 540, "end": 1050}]
    assert (band["days"], band["days_open"]) == (1, 1)
    assert band["description"].startswith("Monday to Friday")


def test_band_today_closed():
    sunday = datetime(2026, 11, 8, 15, 0, tzinfo=UTC)
    band = _band([_agent(1, _WEEKDAYS)], DashboardRange.TODAY, sunday)
    assert band["kind"] == "same"
    assert band["ranges"] == []
    assert band["days_open"] == 0


def test_band_over_days_same_every_day():
    band = _band([_agent(1, [_NINE_TO_530] * 7)], DashboardRange.LAST_7_DAYS, _MONDAY)
    assert band["kind"] == "same"
    assert band["ranges"] == [{"start": 540, "end": 1050}]
    assert (band["days"], band["days_open"]) == (7, 7)


def test_band_over_days_that_differ_is_the_hours_open_on_most_days():
    # Weekdays 9-5:30, Saturday 10-2: 10-2 is open on 6 of 7 days, 9-5:30 on
    # 5; Saturday's hours alone are on one day, so they add nothing.
    days = [_NINE_TO_530] * 5 + [[("10:00", "14:00")], []]
    band = _band([_agent(1, days)], DashboardRange.LAST_7_DAYS, _MONDAY)
    assert band["kind"] == "most_days"
    assert band["ranges"] == [{"start": 540, "end": 1050}]
    assert (band["days"], band["days_open"]) == (7, 6)


def test_band_over_days_with_nothing_open_on_most_days():
    days = [_NINE_TO_530] * 3 + [[], [], [], []]
    band = _band([_agent(1, days)], DashboardRange.LAST_30_DAYS, _MONDAY)
    assert band["kind"] == "most_days"
    assert band["ranges"] == []
    assert band["days"] == 30


def test_band_only_when_the_agents_share_hours():
    same = [_agent(1, _WEEKDAYS), _agent(2, _WEEKDAYS)]
    assert _band(same, DashboardRange.TODAY, _MONDAY)["kind"] == "same"
    differ = [_agent(1, _WEEKDAYS), _agent(2, [_NINE_TO_530] * 7)]
    band = _band(differ, DashboardRange.TODAY, _MONDAY)
    assert band["kind"] == "differ"
    assert band["ranges"] == [] and band["description"] is None
    # An archived agent with no calls isn't shown, so it doesn't count.
    archived = [_agent(1, _WEEKDAYS), _agent(2, [_NINE_TO_530] * 7, "archived")]
    assert _band(archived, DashboardRange.TODAY, _MONDAY)["kind"] == "same"


def test_no_band_without_hours_as_times():
    band = _band([_agent(1, None)], DashboardRange.TODAY, _MONDAY)
    assert band["kind"] == "none" and band["ranges"] == []
