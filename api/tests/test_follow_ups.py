"""Follow-ups: which calls need a person, their order, the done mark and
this week's summary. Pure functions; no database."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from api.services.dashboard.calls import CallResult, CallView
from api.services.dashboard.follow_ups import (
    LOOKBACK,
    FollowUp,
    FollowUpFilter,
    FollowUpKind,
    FollowUpStatus,
    done_mark,
    follow_up_row,
    follow_ups,
    kind_counts,
    matches,
    ordered,
    text_matches,
    week_summary,
)
from api.services.dashboard.service import follow_up_window
from api.services.dashboard.summary import DashboardRange

NOW = datetime(2026, 11, 6, 15, 0, tzinfo=UTC)


def _call(
    run_id,
    result,
    *,
    hours_ago,
    caller="+353871111111",
    mark=None,
    callback=None,
    review=None,
    kind_marks=None,
):
    return CallView(
        run_id=run_id,
        workflow_id=14,
        workflow_name="Bia Bistro bookings",
        created_at=NOW - timedelta(hours=hours_ago),
        result=result,
        duration_seconds=60.0,
        has_recording=True,
        caller_number=caller,
        caller_name=None,
        call_reason=None,
        callback_number=callback,
        follow_up_mark=mark,
        review=review,
        follow_up_marks=kind_marks,
    )


def _done(hours_ago, who="Maria"):
    return {"done_at": (NOW - timedelta(hours=hours_ago)).isoformat(), "done_by": who}


def _kinds(items):
    return {i.call.run_id: i.kind for i in items}


def test_callbacks_and_unanswered_transfers_need_a_person():
    items = follow_ups(
        [
            _call(1, CallResult.CALLBACK_REQUESTED, hours_ago=3),
            _call(
                2, CallResult.TRANSFER_NOT_ANSWERED, hours_ago=2, caller="+353872222222"
            ),
            _call(3, CallResult.HANDLED, hours_ago=1),
            _call(4, CallResult.PASSED_TO_TEAM, hours_ago=1),
            _call(5, CallResult.HUNG_UP_SILENT, hours_ago=1, caller="+353873333333"),
        ]
    )
    assert _kinds(items) == {
        1: FollowUpKind.CALLBACK,
        2: FollowUpKind.TRANSFER_NOT_ANSWERED,
    }


def test_repeat_caller_who_never_reached_anyone():
    items = follow_ups(
        [
            _call(1, CallResult.HUNG_UP_SILENT, hours_ago=5),
            _call(2, CallResult.NOT_CONNECTED, hours_ago=4),
            _call(3, CallResult.HUNG_UP_EARLY, hours_ago=3),
        ]
    )
    assert _kinds(items) == {3: FollowUpKind.REPEAT_CALLER}
    assert items[0].repeat_count == 3
    assert items[0].first_call_at == NOW - timedelta(hours=5)


def test_caller_reached_later_is_not_a_repeat_caller():
    items = follow_ups(
        [
            _call(1, CallResult.HUNG_UP_SILENT, hours_ago=5),
            _call(2, CallResult.HUNG_UP_SILENT, hours_ago=4),
            _call(3, CallResult.HANDLED, hours_ago=3),
            _call(4, CallResult.HUNG_UP_SILENT, hours_ago=2),
        ]
    )
    assert items == []


def test_withheld_numbers_are_never_grouped_as_repeat_callers():
    items = follow_ups(
        [
            _call(1, CallResult.HUNG_UP_SILENT, hours_ago=5, caller=None),
            _call(2, CallResult.HUNG_UP_SILENT, hours_ago=4, caller=None),
        ]
    )
    assert items == []


def test_same_number_written_differently_is_one_caller():
    items = follow_ups(
        [
            _call(1, CallResult.HUNG_UP_SILENT, hours_ago=5, caller="+353 87 111 1111"),
            _call(2, CallResult.HUNG_UP_SILENT, hours_ago=4, caller="+353871111111"),
        ]
    )
    assert _kinds(items) == {2: FollowUpKind.REPEAT_CALLER}


def test_unanswered_transfer_on_a_repeat_caller_stays_one_item():
    items = follow_ups(
        [
            _call(1, CallResult.HUNG_UP_SILENT, hours_ago=5),
            _call(2, CallResult.TRANSFER_NOT_ANSWERED, hours_ago=4),
        ]
    )
    assert _kinds(items) == {2: FollowUpKind.TRANSFER_NOT_ANSWERED}
    assert items[0].repeat_count == 2


def test_open_items_grouped_by_caller_longest_waiting_first():
    items = follow_ups(
        [
            _call(
                1, CallResult.CALLBACK_REQUESTED, hours_ago=1, caller="+353870000001"
            ),
            _call(
                2, CallResult.CALLBACK_REQUESTED, hours_ago=6, caller="+353870000002"
            ),
            _call(
                3, CallResult.TRANSFER_NOT_ANSWERED, hours_ago=2, caller="+353870000002"
            ),
            _call(
                4, CallResult.CALLBACK_REQUESTED, hours_ago=4, caller="+353870000003"
            ),
            _call(
                5,
                CallResult.CALLBACK_REQUESTED,
                hours_ago=8,
                caller="+353870000004",
                mark=_done(1),
            ),
        ]
    )
    open_items = ordered(items, FollowUpStatus.OPEN)
    # Caller 2 has waited longest (6 h), so both of theirs come first.
    assert [i.call.run_id for i in open_items] == [2, 3, 4, 1]
    assert [i.call.run_id for i in ordered(items, FollowUpStatus.DONE)] == [5]


def test_done_items_newest_done_first():
    items = follow_ups(
        [
            _call(
                1,
                CallResult.CALLBACK_REQUESTED,
                hours_ago=9,
                mark=_done(5),
                caller="+353870000001",
            ),
            _call(
                2,
                CallResult.CALLBACK_REQUESTED,
                hours_ago=8,
                mark=_done(1),
                caller="+353870000002",
            ),
        ]
    )
    assert [i.call.run_id for i in ordered(items, FollowUpStatus.DONE)] == [2, 1]


def test_done_row_says_who_and_when():
    item = follow_ups(
        [_call(1, CallResult.CALLBACK_REQUESTED, hours_ago=3, mark=_done(1))]
    )[0]
    row = follow_up_row(item)
    assert row["done_by"] == "Maria"
    assert row["done_at"] == NOW - timedelta(hours=1)
    assert row["kind"] == FollowUpKind.CALLBACK


def test_callers_without_a_number_group_by_callback_number():
    items = follow_ups(
        [
            _call(
                1,
                CallResult.CALLBACK_REQUESTED,
                hours_ago=3,
                caller=None,
                callback="087 000 0009",
            ),
            _call(2, CallResult.CALLBACK_REQUESTED, hours_ago=2, caller=None),
        ]
    )
    keys = {i.call.run_id: i.group_key for i in items}
    assert keys == {1: "0870000009", 2: "call-2"}


def test_week_summary_counts_and_usual_wait():
    items = follow_ups(
        [
            _call(
                1,
                CallResult.CALLBACK_REQUESTED,
                hours_ago=5,
                mark=_done(4),
                caller="+353870000001",
            ),
            _call(
                2,
                CallResult.CALLBACK_REQUESTED,
                hours_ago=10,
                mark=_done(7),
                caller="+353870000002",
            ),
            _call(
                3, CallResult.CALLBACK_REQUESTED, hours_ago=2, caller="+353870000003"
            ),
            # Raised last month, done this week: sorted counts it, raised doesn't.
            _call(
                4,
                CallResult.CALLBACK_REQUESTED,
                hours_ago=24 * 10,
                mark=_done(30),
                caller="+353870000004",
            ),
        ]
    )
    week = week_summary(items, NOW)
    assert week["raised"] == 3
    assert week["sorted"] == 3
    # Waits: 1 h, 3 h, 210 h -> median 3 h.
    assert week["median_wait_minutes"] == 180


def test_week_summary_with_nothing_done():
    items = follow_ups([_call(1, CallResult.CALLBACK_REQUESTED, hours_ago=2)])
    assert week_summary(items, NOW) == {
        "raised": 1,
        "sorted": 0,
        "median_wait_minutes": None,
    }


def test_kind_counts_lists_every_kind():
    items = follow_ups([_call(1, CallResult.CALLBACK_REQUESTED, hours_ago=2)])
    assert kind_counts(items) == {
        "callback": 1,
        "transfer_not_answered": 0,
        "repeat_caller": 0,
        "unanswered_question": 0,
        "time_was_full": 0,
        "other_language": 0,
        "emergency": 0,
    }


def test_done_mark_names_the_member():
    mark = done_mark(user_id=7, name=None, email="maria@trattoria.ie", now=NOW)
    assert mark == {
        "done_at": NOW.isoformat(),
        "done_by_user_id": 7,
        "done_by": "maria",
    }
    assert (
        done_mark(user_id=7, name="Maria Keane", email=None, now=NOW)["done_by"]
        == "Maria Keane"
    )


def _review(questions=(), full=False, summary="Asked about gluten-free pasta."):
    return {
        "summary": summary,
        "reason": "questions",
        "reason_label": "Questions",
        "unanswered_questions": list(questions),
        "time_was_full": full,
    }


def test_call_review_raises_its_own_follow_ups():
    items = follow_ups(
        [
            _call(1, CallResult.HANDLED, hours_ago=3, review=_review(["Gluten-free?"])),
            _call(2, CallResult.HANDLED, hours_ago=2, review=_review(full=True)),
            # A booking made anyway: the full time needs nobody.
            _call(3, CallResult.BOOKING_MADE, hours_ago=2, review=_review(full=True)),
            _call(4, CallResult.HANDLED, hours_ago=1, review=_review()),
        ]
    )
    assert sorted((i.call.run_id, i.kind) for i in items) == [
        (1, FollowUpKind.UNANSWERED_QUESTION),
        (2, FollowUpKind.TIME_WAS_FULL),
    ]
    row = follow_up_row(items[0])
    assert row["questions"] == ["Gluten-free?"]
    assert row["summary"] == "Asked about gluten-free pasta."


def test_one_call_can_need_a_callback_and_an_answer_each_done_on_its_own():
    call = _call(
        1,
        CallResult.CALLBACK_REQUESTED,
        hours_ago=2,
        review=_review(["Gluten-free?"]),
        kind_marks={"unanswered_question": _done(1)},
    )
    items = {i.kind: i for i in follow_ups([call])}
    assert set(items) == {FollowUpKind.CALLBACK, FollowUpKind.UNANSWERED_QUESTION}
    assert not items[FollowUpKind.CALLBACK].done
    assert items[FollowUpKind.UNANSWERED_QUESTION].done
    assert follow_up_row(items[FollowUpKind.CALLBACK])["questions"] == []
    assert [i.kind for i in ordered(list(items.values()), FollowUpStatus.OPEN)] == [
        FollowUpKind.CALLBACK
    ]


# ---------- The page's controls: dates, kind, search, All ----------

DUBLIN = ZoneInfo("Europe/Dublin")


def test_window_defaults_to_the_whole_follow_ups_window():
    for range_ in (None, DashboardRange.LAST_30_DAYS):
        start, end = follow_up_window(
            range_=range_, start_date=None, end_date=None, tz=DUBLIN, now=NOW
        )
        assert (start, end) == (NOW - LOOKBACK, None)


def test_window_today_and_seven_days_start_at_local_midnight():
    start, end = follow_up_window(
        range_=DashboardRange.TODAY, start_date=None, end_date=None, tz=DUBLIN, now=NOW
    )
    assert start == datetime(2026, 11, 6, 0, 0, tzinfo=DUBLIN) and end is None
    start, _ = follow_up_window(
        range_=DashboardRange.LAST_7_DAYS,
        start_date=None,
        end_date=None,
        tz=DUBLIN,
        now=NOW,
    )
    assert start == datetime(2026, 10, 31, 0, 0, tzinfo=DUBLIN)


def test_window_days_picked_by_hand_include_the_last_day_and_stay_in_range():
    start, end = follow_up_window(
        range_=DashboardRange.TODAY,
        start_date=date(2026, 11, 2),
        end_date=date(2026, 11, 3),
        tz=DUBLIN,
        now=NOW,
    )
    assert start == datetime(2026, 11, 2, 0, 0, tzinfo=DUBLIN)
    assert end == datetime(2026, 11, 4, 0, 0, tzinfo=DUBLIN)
    # Before the window: clamped to it, never further back.
    start, end = follow_up_window(
        range_=None,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 2),
        tz=DUBLIN,
        now=NOW,
    )
    assert start == end == NOW - LOOKBACK


def _item(kind=FollowUpKind.CALLBACK, **call):
    return FollowUp(kind, _call(1, CallResult.CALLBACK_REQUESTED, **call))


def test_filter_by_dates_and_kind():
    item = _item(hours_ago=30)
    assert matches(item, FollowUpFilter())
    assert not matches(item, FollowUpFilter(start=NOW - timedelta(hours=24)))
    assert matches(item, FollowUpFilter(end=NOW - timedelta(hours=24)))
    assert not matches(item, FollowUpFilter(kind=FollowUpKind.TIME_WAS_FULL))
    # The kind chips count without their own kind.
    assert matches(item, FollowUpFilter(kind=FollowUpKind.TIME_WAS_FULL), kind=False)


def test_search_finds_the_number_written_any_way_and_the_database_hits():
    item = _item(hours_ago=1, caller="+353871234567")
    assert text_matches(item, "087 123 4567")
    assert text_matches(item, "1234567")
    assert not text_matches(item, "0861234567")
    assert not matches(item, FollowUpFilter(text="gluten", found=frozenset()))
    # What was said on the call is found by the database search.
    assert matches(item, FollowUpFilter(text="gluten", found=frozenset({1})))


def test_status_all_lists_to_do_then_done():
    calls = [
        _call(1, CallResult.CALLBACK_REQUESTED, hours_ago=3, caller="+353870000001"),
        _call(
            2,
            CallResult.CALLBACK_REQUESTED,
            hours_ago=2,
            caller="+353870000002",
            mark={"done_at": (NOW - timedelta(hours=1)).isoformat()},
        ),
    ]
    items = follow_ups(calls)
    shown = ordered(items, FollowUpStatus.ALL)
    assert [(i.call.run_id, i.done) for i in shown] == [(1, False), (2, True)]


def test_a_caller_in_another_language_and_an_emergency_raise_their_own_follow_ups():
    polish = {
        **_review(summary="Asked in Polish about a table."),
        "caller_language": "pl",
        "other_language": True,
    }
    english = {**_review(), "caller_language": "en", "other_language": False}
    # Spoken in a language the agent has switched on: nobody needs to act.
    spoken = {**_review(), "caller_language": "pl", "other_language": False}
    emergency = {
        **_review(summary="Described chest pain; was told to dial 112."),
        "emergency": True,
    }
    items = follow_ups(
        [
            _call(1, CallResult.CALLBACK_REQUESTED, hours_ago=3, review=polish),
            _call(2, CallResult.HANDLED, hours_ago=3, review=english),
            _call(3, CallResult.HANDLED, hours_ago=3, review=spoken),
            _call(4, CallResult.HUNG_UP_EARLY, hours_ago=2, review=emergency),
        ]
    )
    assert sorted((i.call.run_id, i.kind.value) for i in items) == [
        (1, "callback"),
        (1, "other_language"),
        (4, "emergency"),
    ]
    by_kind = {i.kind: i for i in items}
    row = follow_up_row(by_kind[FollowUpKind.OTHER_LANGUAGE])
    assert row["caller_language"] == "pl"
    assert row["caller_language_name"] == "Polish"
    assert row["has_recording"] is True
    assert follow_up_row(by_kind[FollowUpKind.EMERGENCY])["caller_language"] is None


def test_language_and_emergency_follow_ups_are_done_on_their_own():
    review = {
        **_review(),
        "caller_language": "pt",
        "other_language": True,
        "emergency": True,
    }
    call = _call(
        1,
        CallResult.CALLBACK_REQUESTED,
        hours_ago=2,
        review=review,
        kind_marks={"other_language": _done(1)},
    )
    items = {i.kind: i for i in follow_ups([call])}
    assert items[FollowUpKind.OTHER_LANGUAGE].done
    assert not items[FollowUpKind.EMERGENCY].done
    assert not items[FollowUpKind.CALLBACK].done


def test_old_reviews_raise_no_language_or_emergency_follow_up():
    items = follow_ups([_call(1, CallResult.HANDLED, hours_ago=2, review=_review())])
    assert items == []
