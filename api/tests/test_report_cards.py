"""Report cards: the packs, reading what the agent wrote down, each card's
numbers and the owner's layout. Pure functions; no database."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from api.schemas.opening_hours import OpeningHours
from api.services.call_review.categories import CLINIC, GENERAL, RESTAURANT, TRADES
from api.services.dashboard.calls import CallResult, call_view
from api.services.dashboard.summary import tiles
from api.services.report_cards import cards as c
from api.services.report_cards import fields
from api.services.report_cards.catalogue import (
    PACKS,
    Card,
    CardSize,
    Pack,
    pack_for_template,
)
from api.services.report_cards.layout import (
    CardChoice,
    LayoutError,
    StoredLayout,
    average,
    effective_cards,
    parse_layout,
    reset_pack,
    save_pack,
)
from api.services.report_cards.service import RangeError, ReportRange, report_bounds

DUBLIN = ZoneInfo("Europe/Dublin")
# Saturday 7 November 2026, 3 pm in Dublin.
NOW = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)
BOOKED_LOG_RESULT = {"booking_outcome": "booked"}


def _call(
    run_id=1,
    *,
    at=None,
    gathered=None,
    review=None,
    speech=True,
    booked=False,
    caller="+353871234567",
    marks=None,
    workflow_id=14,
):
    gathered = dict(gathered or {})
    gathered.setdefault("call_tags", ["end_call", "user_speech"] if speech else [])
    if booked:
        gathered["tool_results"] = [
            {
                "function_name": "mcp__google_calendar__book_appointment",
                "status": "completed",
                "arguments": {"slot_id": "2026-11-14T19:00:00+00:00"},
                "result": '{"booked": true, "event_id": "e1", "starts_at": "2026-11-14T19:00:00+00:00"}',
            }
        ]
    annotations = {}
    if review is not None:
        annotations["call_review"] = {"version": 1, **review}
    if marks:
        annotations["follow_up_kinds"] = marks
    row = {
        "id": run_id,
        "workflow_id": workflow_id,
        "workflow_name": "Front desk",
        "created_at": at or NOW - timedelta(hours=1),
        "is_completed": True,
        "has_recording": False,
        "gathered_context": gathered,
        "usage_info": {"call_duration_seconds": 60},
        "initial_context": {"caller_number": caller},
        "annotations": annotations,
        "transfer_hint": False,
    }
    return c.ReportCall(view=call_view(row, None, NOW), gathered=gathered)


def _span(days=7, hours=None, without=()):
    end = NOW
    start = (
        datetime(2026, 11, 1, tzinfo=DUBLIN) if days == 7 else NOW - timedelta(hours=1)
    )
    return c.Span(
        start=start,
        end=end,
        previous_start=start - (end - start),
        previous_end=start,
        tz=DUBLIN,
        now=NOW,
        hours=hours or {},
        agents_without_hours=without,
    )


def _hours(**days):
    """Opening hours: Tuesday to Sunday 12:00-22:00, closed Monday."""
    week = [[]] + [[{"open": "12:00", "close": "22:00"}]] * 6
    return OpeningHours.model_validate(
        {"timezone": "Europe/Dublin", "days": week, **days}
    )


# --- reading what the agent wrote down ------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("4", 4),
        (4, 4),
        (4.0, 4),
        ("4 people", 4),
        ("four", 4),
        ("Four people", 4),
        ("a table for two", 2),
        ("12", 12),
        ("", None),
        (None, None),
        ("4 or 5", None),
        ("four or five", None),
        ("a couple", None),
        ("2.5", None),
        ("0", None),
        ("500", None),
        (True, None),
        ([4], None),
    ],
)
def test_party_size_reads_only_one_clear_number(value, expected):
    assert fields.party_size(value) == expected


@pytest.mark.parametrize(
    "address, expected",
    [
        ("15 Riverside Park, Douglas", "Douglas"),
        ("26 oakfield drive, togher", "Togher"),
        ("Main Street, Midleton, Co. Cork", "Midleton"),
        ("Main Street, Midleton, Co. Cork, T12 X4F6", "Midleton"),
        ("Co. Cork", "Co. Cork"),
        ("Unit 4, Naas Road, Dublin 12", "Dublin 12"),
        ("Ballincollig", "Ballincollig"),
        ("Riverside Park", fields.UNCLEAR),
        ("15 Riverside Park", fields.UNCLEAR),
        ("the house beside the church on the hill", fields.UNCLEAR),
        ("", None),
        (None, None),
    ],
)
def test_area_is_the_town_or_county_and_unclear_otherwise(address, expected):
    assert fields.area(address) == expected


def test_question_wording_groups_case_and_punctuation():
    assert fields.question_key("Do you have gluten-free pasta?") == fields.question_key(
        "do you have gluten free pasta"
    )


# --- packs -----------------------------------------------------------------------


def test_each_template_gets_its_pack():
    assert pack_for_template("restaurant").pack == Pack.RESTAURANT
    assert pack_for_template("clinic").pack == Pack.CLINIC
    assert pack_for_template("trades").pack == Pack.TRADES
    assert pack_for_template("telephony").pack == Pack.VOIP
    assert pack_for_template("salon").pack == Pack.STANDARD
    assert pack_for_template(None).pack == Pack.STANDARD


def test_every_pack_has_the_shared_cards_once():
    shared = {
        Card.CALLS_ANSWERED,
        Card.CALLERS_WANTED,
        Card.BUSIEST_TIMES,
        Card.UNANSWERED_QUESTIONS,
        Card.FOLLOW_UPS,
        Card.AFTER_HOURS,
        Card.AGENT_PERFORMANCE,
    }
    for pack in [*PACKS.values(), pack_for_template("general")]:
        assert shared <= set(pack.keys), pack.pack
        assert len(set(pack.keys)) == len(pack.keys)


def test_money_cards_only_in_packs_with_an_average():
    for pack in PACKS.values():
        estimates = [card for card in pack.cards if card.estimate]
        assert bool(estimates) == (pack.value_unit is not None)
        assert all(card.size == CardSize.KPI and not card.email for card in estimates)


def test_standard_pack_words_bookings_for_the_business():
    salon = pack_for_template("salon")
    assert salon.spec(Card.BOOKINGS_TAKEN).title == "Appointments booked"


# --- shared cards ------------------------------------------------------------------


def test_calls_answered_matches_home_and_counts_closed_calls():
    monday = datetime(2026, 11, 2, 12, 0, tzinfo=DUBLIN)
    calls = [_call(1, at=monday), _call(2, at=NOW - timedelta(hours=1))]
    card = c.calls_answered(calls, [], _span(hours={14: _hours()}))
    assert card["calls"] == tiles([x.view for x in calls])["calls"] == 2
    assert card["after_hours"] == 1
    assert card["change"] is None  # too few to compare
    assert c.calls_answered(calls, [], _span())["after_hours"] is None


def test_callers_wanted_by_day_in_the_templates_order():
    sat = datetime(2026, 11, 7, 12, 0, tzinfo=DUBLIN)
    calls = [
        _call(1, at=sat, review={"reason": "other", "reason_label": "Other"}),
        _call(2, at=sat, review={"reason": "questions", "reason_label": "Q"}),
        _call(3, at=sat, review={"reason": "reservations", "reason_label": "R"}),
        _call(4, at=sat - timedelta(days=1)),  # not reviewed yet
    ]
    card = c.callers_wanted(calls, RESTAURANT, _span())
    assert [s["key"] for s in card["series"]] == [
        "reservations",
        "questions",
        "other",
        "not_reviewed",
    ]
    assert card["series"][0]["label"] == "Reservations"
    assert card["unit"] == "day" and len(card["buckets"]) == 7
    assert card["buckets"][-1]["counts"] == {
        "other": 1,
        "questions": 1,
        "reservations": 1,
    }
    assert card["buckets"][-2]["total"] == 1


def test_one_day_report_is_by_hour():
    card = c.callers_wanted([_call()], RESTAURANT, _span(days=1))
    assert card["unit"] == "hour"
    assert card["buckets"][0]["hour"] == 8


def test_busiest_tip_only_when_one_slot_stands_out():
    friday = datetime(2026, 11, 6, 17, 10, tzinfo=DUBLIN)
    spread = [
        _call(i, at=datetime(2026, 11, 1 + i % 5, 9 + i % 10, tzinfo=DUBLIN))
        for i in range(30)
    ]
    assert c.busiest_times(spread, _span())["tip"] is None
    peak = [_call(100 + i, at=friday + timedelta(minutes=5 * i)) for i in range(10)]
    card = c.busiest_times(spread + peak, _span())
    assert card["tip"] == {
        "weekday": 4,
        "start_hour": 17,
        "end_hour": 19,
        "calls": 10,
        "one_in": 4,
    }
    assert card["grid"][4][17] == 10
    # Too few calls overall: no tip, however lopsided.
    assert c.busiest_times(peak, _span())["tip"] is None


def test_unanswered_questions_grouped_with_latest_call():
    calls = [
        _call(
            1,
            at=NOW - timedelta(days=2),
            review={
                "reason": "questions",
                "unanswered_questions": ["Gluten-free pasta?"],
            },
        ),
        _call(
            2,
            at=NOW - timedelta(days=1),
            review={
                "reason": "questions",
                "unanswered_questions": ["gluten free pasta"],
            },
        ),
        _call(
            3,
            review={
                "reason": "questions",
                "unanswered_questions": ["Is the terrace heated?"],
            },
        ),
    ]
    card = c.unanswered(calls)
    assert card["calls"] == 3
    first = card["groups"][0]
    assert (first["question"], first["count"], first["run_id"]) == (
        "gluten free pasta",
        2,
        2,
    )
    assert card["groups"][1]["count"] == 1


def test_follow_ups_raised_sorted_and_usual_wait():
    done = {"time_was_full": {"done_at": (NOW - timedelta(minutes=30)).isoformat()}}
    calls = [
        _call(
            1,
            at=NOW - timedelta(hours=2),
            review={"reason": "reservations", "time_was_full": True},
            marks=done,
        ),
        _call(2, gathered={"callback_number": "0871112222"}),
    ]
    card = c.follow_up_stats(calls)
    assert (card["raised"], card["sorted"], card["open"]) == (2, 1, 1)
    assert card["median_wait_minutes"] == 90
    assert {k["kind"] for k in card["kinds"]} == {"callback", "time_was_full"}


def test_after_hours_needs_opening_hours():
    monday = datetime(2026, 11, 2, 12, 0, tzinfo=DUBLIN)
    calls = [
        _call(1, at=monday, booked=True),
        _call(2, at=monday, gathered={"callback_number": "1"}),
    ]
    card = c.after_hours(calls, _span(hours={14: _hours()}))
    assert (card["calls"], card["bookings"], card["callbacks"]) == (2, 1, 1)
    unknown = c.after_hours(calls, _span(without=["Front desk"]))
    assert unknown["hours_set"] is False and unknown["calls"] is None
    assert unknown["agents_without_hours"] == ["Front desk"]


def test_agent_performance_uses_homes_results():
    calls = [
        _call(1, booked=True),
        _call(2),
        _call(3, gathered={"callback_number": "1"}),
        _call(4, speech=False),
    ]
    card = c.agent_performance(calls)
    home = tiles([x.view for x in calls])
    assert card["handled"] == home["handled"] == 2
    assert card["handled_percent"] == home["handled_percent"] == 50
    assert card["needed_person"] == 1
    assert card["hung_up_silent"] == home["hung_up_silent"] == 1
    assert card["results"] == {
        "booking_made": 1,
        "handled": 1,
        "callback_requested": 1,
        "hung_up_silent": 1,
    }


# --- restaurant ------------------------------------------------------------------


def test_covers_sum_booked_party_sizes_and_count_the_rest_apart():
    calls = [
        _call(1, booked=True, gathered={"party_size": "4"}),
        _call(2, booked=True, gathered={"party_size": "four people"}),
        _call(3, booked=True, gathered={"party_size": "4 or 5"}),
        _call(4, booked=True, gathered={"party_size": ""}),
        _call(5, gathered={"party_size": "10"}),  # no booking made
    ]
    card = c.covers(calls, [])
    assert card["covers"] == 8
    assert card["bookings_with_size"] == 2
    assert (card["unreadable"], card["not_given"]) == (1, 1)
    assert card["average_party"] == 4.0
    assert c.bookings(calls, [])["count"] == 4
    assert c.bookings(calls, [])["percent_of_calls"] == 80


def test_tables_full_counts_covers_and_when():
    full = {"reason": "reservations", "time_was_full": True}
    calls = [
        _call(
            1,
            review=full,
            gathered={
                "party_size": "6",
                "booking_date": "2026-11-13",
                "booking_time": "20:00",
            },
        ),
        _call(
            2,
            review=full,
            gathered={
                "party_size": "4",
                "booking_date": "2026-11-14",
                "booking_time": "20:00",
            },
        ),
        _call(
            3,
            review=full,
            gathered={
                "party_size": "x",
                "booking_date": "2026-11-14",
                "booking_time": "20:30",
            },
        ),
        _call(
            4, review=full, booked=True, gathered={"party_size": "2"}
        ),  # booked anyway
    ]
    card = c.tables_full(calls, [], _span())
    assert (card["count"], card["covers"], card["without_size"]) == (3, 10, 1)
    assert card["mostly_days"] == [5]  # Saturday: 2 of 3
    assert card["mostly_hour"] == 20


def test_days_filling_are_the_next_two_weeks_with_closed_days():
    calls = [
        _call(
            1, booked=True, gathered={"party_size": "4", "booking_date": "2026-11-08"}
        ),
        _call(
            2, booked=True, gathered={"party_size": "2", "booking_date": "2026-11-08"}
        ),
        _call(
            3, booked=True, gathered={"party_size": "", "booking_date": "2026-11-10"}
        ),
        _call(
            4, booked=True, gathered={"party_size": "2", "booking_date": "2027-01-10"}
        ),
        _call(5, booked=True, gathered={"party_size": "2"}),
    ]
    card = c.days_filling(calls, _span(hours={14: _hours()}))
    days = {d["date"]: d for d in card["days"]}
    assert len(card["days"]) == 14 and card["days"][0]["date"] == date(2026, 11, 7)
    assert days[date(2026, 11, 8)]["covers"] == 6
    assert days[date(2026, 11, 10)]["bookings"] == 1
    assert days[date(2026, 11, 9)]["closed"] is True  # Monday
    assert (card["without_size"], card["later"], card["without_day"]) == (1, 1, 1)


def test_special_requests_from_tags_and_old_reviews_apart():
    calls = [
        _call(
            1,
            review={
                "reason": "reservations",
                "request_tags": ["allergies_diets", "seating"],
            },
        ),
        _call(
            2, review={"reason": "reservations", "request_tags": ["allergies_diets"]}
        ),
        _call(3, review={"reason": "reservations", "request_tags": []}),
        _call(
            4,
            review={"reason": "reservations"},
            gathered={"special_requests": "a birthday"},
        ),
        _call(5, review={"reason": "reservations"}),
    ]
    card = c.special_requests(calls, RESTAURANT)
    assert card["tags"] == [
        {"key": "allergies_diets", "label": "Allergies & diets", "count": 2},
        {"key": "seating", "label": "Seating preference", "count": 1},
    ]
    assert (card["calls_with_requests"], card["tagged_calls"], card["not_tagged"]) == (
        2,
        3,
        1,
    )
    assert c.special_requests(calls, CLINIC) is None


def test_build_cards_restaurant_pack_and_the_estimate_needs_an_average():
    calls = [
        _call(
            1,
            booked=True,
            gathered={"party_size": "4"},
            review={"reason": "reservations"},
        )
    ]
    pack = PACKS[Pack.RESTAURANT]
    out = c.build_cards(
        pack=pack, reasons=RESTAURANT, calls=calls, previous=[], span=_span()
    )
    assert set(out) == set(pack.keys)
    assert out[Card.BOOKINGS_VALUE] is None
    out = c.build_cards(
        pack=pack,
        reasons=RESTAURANT,
        calls=calls,
        previous=[],
        span=_span(),
        average=Decimal("35"),
        wanted=[Card.BOOKINGS_VALUE],
    )
    assert list(out) == [Card.BOOKINGS_VALUE]
    assert out[Card.BOOKINGS_VALUE]["value"] == Decimal("140")
    assert out[Card.BOOKINGS_VALUE]["units"] == 4


def test_takeaway_only_where_the_reason_exists():
    pack = pack_for_template("general")
    assert (
        c.build_cards(
            pack=PACKS[Pack.RESTAURANT],
            reasons=RESTAURANT,
            calls=[],
            previous=[],
            span=_span(),
            wanted=[Card.TAKEAWAY],
        )[Card.TAKEAWAY]["count"]
        == 0
    )
    assert (
        c.build_cards(
            pack=PACKS[Pack.RESTAURANT],
            reasons=GENERAL,
            calls=[],
            previous=[],
            span=_span(),
            wanted=[Card.TAKEAWAY],
        )[Card.TAKEAWAY]
        is None
    )
    assert Card.TAKEAWAY not in pack.keys


# --- clinic, trades, voip ------------------------------------------------------------


def test_patient_status_and_appointment_types():
    calls = [
        _call(
            1,
            booked=True,
            gathered={"patient_status": "new", "appointment_type": "check-up"},
        ),
        _call(
            2,
            booked=True,
            gathered={"patient_status": "existing", "appointment_type": "Check-up"},
        ),
        _call(
            3,
            booked=True,
            gathered={"patient_status": "", "appointment_type": "filling"},
        ),
        _call(
            4,
            gathered={
                "patient_status": "returning patient",
                "appointment_type": "check-up",
            },
        ),
    ]
    status = c.patient_status(calls)
    assert (status["new"], status["existing"], status["booked_not_said"]) == (1, 2, 1)
    types = c.appointment_types(calls)["types"]
    assert types[0] == {"label": "Check-up", "calls": 3, "booked": 2}
    assert types[1] == {"label": "Filling", "calls": 1, "booked": 1}


def test_trades_emergencies_areas_and_waiting():
    late = datetime(2026, 11, 6, 23, 30, tzinfo=DUBLIN)
    calls = [
        _call(
            1,
            at=late,
            gathered={
                "urgency": "emergency",
                "job_address": "15 Riverside Park, Douglas",
                "callback_number": "1",
            },
            review={"reason": "urgent"},
        ),
        _call(
            2,
            at=late,
            gathered={"urgency": "Emergency", "job_address": "4 Main St, Douglas"},
            review={"reason": "urgent"},
        ),
        _call(
            3,
            gathered={"urgency": "no rush", "job_address": "Riverside Park"},
            review={"reason": "new_job"},
        ),
    ]
    span = _span(hours={14: _hours()})
    by_hour = c.emergencies_by_hour(calls, span)
    assert by_hour["count"] == 2 and by_hour["hours"][23] == 2
    assert by_hour["after_hours"] == 2
    where = c.areas(calls)
    assert where["areas"] == [{"label": "Douglas", "count": 2}]
    assert where["unclear"] == 1
    wait = c.waiting(calls, span)
    assert wait["count"] == 1 and wait["items"][0]["area"] == "Douglas"
    callouts = c.after_hours_callouts(calls, [], span)
    assert callouts["count"] == 2
    jobs = c.build_cards(
        pack=PACKS[Pack.TRADES],
        reasons=TRADES,
        calls=calls,
        previous=[],
        span=span,
        wanted=[Card.JOBS_QUOTES],
    )
    assert jobs[Card.JOBS_QUOTES]["count"] == 1


def test_voip_issues_spikes_and_repeat_callers():
    hour = datetime(2026, 11, 3, 10, 5, tzinfo=DUBLIN)
    outage = [
        _call(
            i,
            at=hour + timedelta(minutes=i),
            caller=f"+35387000000{i}",
            review={"reason": "speak_to_someone"},
        )
        for i in range(5)
    ]
    repeat = [
        _call(10 + i, at=NOW - timedelta(hours=i + 1), caller="+353 87 555 0101")
        for i in range(3)
    ]
    calls = outage + repeat
    issues = c.issues_by_type(calls, GENERAL)["types"]
    assert issues[0]["key"] == "speak_to_someone" and issues[0]["count"] == 5
    spikes = c.call_spikes(calls, _span())
    assert spikes["spikes"][0]["calls"] == 5
    assert spikes["by_hour"][10] == 5
    repeats = c.repeat_callers(calls)
    assert (repeats["callers"], repeats["calls"]) == (1, 3)
    split = c.sorted_split(calls, [])
    assert split["sorted"]["count"] == 8


def test_estimate_shows_only_with_an_average():
    assert c.estimate(None, 10, 5, "cover") is None
    card = c.estimate(Decimal("35"), 142, 121, "cover")
    assert card["value"] == Decimal("4970") and card["change"] == Decimal("735")


# --- layout ------------------------------------------------------------------------


def test_unsaved_layout_is_the_packs_defaults():
    pack = PACKS[Pack.RESTAURANT]
    cards = effective_cards(pack, StoredLayout())
    assert [x.key for x in cards] == list(pack.keys)
    assert all(x.on for x in cards)
    assert {x.key for x in cards if x.email} == {s.key for s in pack.cards if s.email}


def test_saved_layout_keeps_order_drops_unknown_and_adds_new_cards():
    pack = PACKS[Pack.RESTAURANT]
    stored = parse_layout(
        {
            "packs": {
                "restaurant": {
                    "cards": [
                        {"key": "busiest_times", "on": False, "email": True},
                        {"key": "gone", "on": True},
                        {"key": "calls_answered", "on": True},
                    ]
                }
            }
        }
    )
    cards = effective_cards(pack, stored)
    assert [x.key for x in cards[:2]] == ["busiest_times", "calls_answered"]
    assert cards[0].on is False and cards[0].email is True
    assert len(cards) == len(pack.keys)


def test_save_validates_and_reset_keeps_the_average():
    pack = PACKS[Pack.RESTAURANT]
    stored = StoredLayout()
    save_pack(
        stored,
        pack,
        [CardChoice(key="covers_booked", on=False)],
        Decimal("35"),
        by="Niamh",
        now=NOW,
    )
    assert effective_cards(pack, stored)[0].key == "covers_booked"
    assert average(pack, stored) == Decimal("35.00")
    with pytest.raises(LayoutError):
        save_pack(stored, pack, [CardChoice(key="areas")], None, by=None, now=NOW)
    with pytest.raises(LayoutError):
        save_pack(stored, pack, [CardChoice(key="areas")] * 2, None, by=None, now=NOW)
    with pytest.raises(LayoutError):
        save_pack(stored, PACKS[Pack.VOIP], [], Decimal("5"), by=None, now=NOW)
    reset_pack(stored, pack)
    assert effective_cards(pack, stored)[0].key == "calls_answered"
    assert average(pack, stored) == Decimal("35.00")


def test_unreadable_layout_falls_back_to_defaults():
    assert parse_layout({"packs": "x"}).packs == {}
    assert parse_layout(None).packs == {}


# --- periods ------------------------------------------------------------------------


def test_custom_range_compares_with_the_same_length_before():
    bounds = report_bounds(
        ReportRange.CUSTOM, DUBLIN, NOW, date(2026, 11, 1), date(2026, 11, 3)
    )
    assert bounds.start == datetime(2026, 11, 1, tzinfo=DUBLIN)
    assert bounds.end == datetime(2026, 11, 4, tzinfo=DUBLIN)
    assert bounds.previous_end == bounds.start
    assert bounds.end - bounds.start == bounds.previous_end - bounds.previous_start
    # Running into today: up to now, and the previous span is just as long.
    today = report_bounds(
        ReportRange.CUSTOM, DUBLIN, NOW, date(2026, 11, 6), date(2026, 11, 7)
    )
    assert today.end == NOW
    assert today.end - today.start == today.previous_end - today.previous_start


@pytest.mark.parametrize(
    "start, end",
    [
        (None, None),
        (date(2026, 11, 5), date(2026, 11, 1)),
        (date(2026, 11, 9), None),
        (date(2025, 1, 1), date(2026, 11, 1)),
    ],
)
def test_bad_custom_ranges_are_refused(start, end):
    with pytest.raises(RangeError):
        report_bounds(ReportRange.CUSTOM, DUBLIN, NOW, start, end)


def test_preset_ranges_are_homes():
    bounds = report_bounds(ReportRange.LAST_7_DAYS, DUBLIN, NOW)
    assert bounds.start == datetime(2026, 11, 1, tzinfo=DUBLIN)
    assert bounds.previous_start == datetime(2026, 10, 25, tzinfo=DUBLIN)
    assert CallResult.BOOKING_MADE  # imported for Home's own names
