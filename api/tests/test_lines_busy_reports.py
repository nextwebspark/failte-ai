"""Turned-away calls (every line busy) on Home, Follow-ups, the report card
and the email. Pure functions; no database."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from api.services.call_review.categories import RESTAURANT, reason_set
from api.services.dashboard.calls import CallResult, call_result, call_view
from api.services.dashboard.follow_ups import FollowUpKind, follow_up_row, follow_ups
from api.services.dashboard.summary import callers_wanted, tiles, turned_away_today
from api.services.email_reports.cards import email_blocks
from api.services.email_reports.periods import Frequency
from api.services.report_cards import cards as c
from api.services.report_cards.catalogue import PACKS, Card, Pack, pack_for_template

DUBLIN = ZoneInfo("Europe/Dublin")
# Saturday 7 November 2026, 9 pm in Dublin.
NOW = datetime(2026, 11, 7, 21, 0, tzinfo=UTC)


def _busy(action="voicemail", *, forward=None, voicemail=None, limit=10):
    gathered = {
        "call_id": "CA1",
        "mapped_call_disposition": "lines_busy",
        "lines_busy": {"action": action, "limit": limit},
    }
    if forward:
        gathered["lines_busy_forward"] = {"result": forward}
    if voicemail is not None:
        gathered["lines_busy_voicemail"] = {"seconds": voicemail, "stored": True}
    return gathered


def _row(run_id, gathered, *, minutes_ago=30, completed=True, caller="+353871234567"):
    return {
        "id": run_id,
        "workflow_id": 14,
        "workflow_name": "Bia Bistro",
        "created_at": NOW - timedelta(minutes=minutes_ago),
        "is_completed": completed,
        "has_recording": bool(gathered.get("lines_busy_voicemail")),
        "gathered_context": gathered,
        "usage_info": {},
        "initial_context": {"caller_number": caller},
        "annotations": {},
        "transfer_hint": False,
    }


def _result(gathered, *, completed=True, minutes_ago=30):
    return call_result(
        is_completed=completed,
        created_at=NOW - timedelta(minutes=minutes_ago),
        gathered_context=gathered,
        usage_info={},
        logs=None,
        now=NOW,
    )


def test_call_result_for_turned_away_calls():
    assert _result(_busy()) == CallResult.LINES_BUSY
    assert _result(_busy(voicemail=20)) == CallResult.LINES_BUSY
    assert _result(_busy("busy_message")) == CallResult.LINES_BUSY
    assert _result(_busy("forward", forward="not_answered")) == CallResult.LINES_BUSY
    # Someone on the team picked up: passed to the team, like any transfer.
    assert _result(_busy("forward", forward="answered")) == CallResult.PASSED_TO_TEAM
    # Still taking a voicemail: on the line, but only for a few minutes.
    assert _result(_busy(), completed=False, minutes_ago=2) == CallResult.IN_PROGRESS
    assert _result(_busy(), completed=False, minutes_ago=15) == CallResult.LINES_BUSY
    # A forward can last as long as any call.
    assert (
        _result(_busy("forward"), completed=False, minutes_ago=15)
        == CallResult.IN_PROGRESS
    )


def test_follow_up_with_call_back_and_voicemail():
    calls = [
        call_view(_row(1, _busy(voicemail=20)), None, NOW),
        call_view(
            _row(2, _busy("forward", forward="answered"), caller="+353861111111"),
            None,
            NOW,
        ),
        call_view(_row(3, _busy("busy_message"), caller="+353862222222"), None, NOW),
    ]
    items = {i.call.run_id: i for i in follow_ups(calls)}
    assert items[1].kind == FollowUpKind.LINES_BUSY
    assert items[3].kind == FollowUpKind.LINES_BUSY
    # Answered by staff: counted, but nothing to follow up.
    assert 2 not in items
    row = follow_up_row(items[1])
    assert row["lines_busy"] == "voicemail"
    assert row["voicemail_seconds"] == 20
    assert row["has_recording"] is True
    assert row["caller_number"] == "+353871234567"
    assert follow_up_row(items[3])["lines_busy"] == "told_busy"


def test_a_caller_turned_away_twice_is_one_item_saying_so():
    calls = [
        call_view(_row(1, _busy(), minutes_ago=50), None, NOW),
        call_view(_row(2, _busy(), minutes_ago=20), None, NOW),
    ]
    latest = [i for i in follow_ups(calls) if i.call.run_id == 2][0]
    assert latest.kind == FollowUpKind.LINES_BUSY
    assert latest.repeat_count == 2


def test_home_counts_and_never_waits_for_a_review():
    calls = [
        call_view(_row(1, _busy(voicemail=20)), None, NOW),
        call_view(_row(2, _busy("forward", forward="answered")), None, NOW),
        call_view(_row(3, _busy("busy_message"), minutes_ago=60 * 24), None, NOW),
    ]
    counted = tiles(calls)
    assert counted["lines_busy"] == 2
    assert counted["passed_to_team"] == 1
    # Not "Not reviewed yet": the agent never took these calls.
    assert callers_wanted(calls) == []
    assert turned_away_today(calls, DUBLIN, NOW) == {
        "calls": 2,
        "forwarded": 1,
        "voicemails": 1,
    }


def _report_call(run_id, gathered, minutes_ago=30):
    return c.ReportCall(
        view=call_view(_row(run_id, gathered, minutes_ago=minutes_ago), None, NOW),
        gathered=gathered,
    )


def _span():
    start = datetime(2026, 11, 1, tzinfo=DUBLIN)
    return c.Span(
        start=start,
        end=NOW,
        previous_start=start - (NOW - start),
        previous_end=start,
        tz=DUBLIN,
        now=NOW,
    )


def test_report_card_counts_and_busiest_times():
    calls = [
        _report_call(1, _busy(voicemail=20)),
        _report_call(2, _busy("forward", forward="answered"), minutes_ago=10),
        _report_call(3, _busy("forward", forward="not_answered"), minutes_ago=40),
        _report_call(4, _busy("busy_message", limit=12), minutes_ago=60 * 24 * 3),
    ]
    card = c.lines_busy(calls, _span())
    assert card["calls"] == 4
    assert card["forwarded"] == 2
    assert card["answered"] == 1
    assert card["voicemails"] == 1
    assert card["no_message"] == 1
    assert card["told_busy"] == 1
    # Saturday (5), 8-9 pm in Dublin, had three of them.
    assert card["busiest"][0] == {"weekday": 5, "hour": 20, "calls": 3}
    assert card["limit"] == 10


def test_turned_away_calls_stay_out_of_the_other_cards():
    calls = [
        _report_call(1, _busy(voicemail=20)),
        _report_call(
            2, {"call_tags": ["end_call", "user_speech"], "call_status": "completed"}
        ),
    ]
    cards = c.build_cards(
        pack=PACKS[Pack.RESTAURANT],
        reasons=reason_set(RESTAURANT),
        calls=calls,
        previous=[],
        span=_span(),
    )
    assert cards[Card.CALLS_ANSWERED]["calls"] == 1
    assert cards[Card.LINES_BUSY]["calls"] == 1
    assert cards[Card.FOLLOW_UPS]["raised"] == 1


def test_every_pack_has_the_card_ticked_for_the_email():
    for pack in [*PACKS.values(), pack_for_template("general")]:
        spec = pack.spec(Card.LINES_BUSY)
        assert spec is not None
        assert spec.title == "Callers who couldn't get through"
        assert spec.email is True


def test_email_block():
    card = {
        "calls": 4,
        "forwarded": 2,
        "answered": 1,
        "voicemails": 1,
        "no_message": 1,
        "told_busy": 1,
        "busiest": [{"weekday": 5, "hour": 20, "calls": 3}],
        "limit": 10,
    }
    pack = PACKS[Pack.RESTAURANT]
    (block,) = email_blocks(
        pack=pack,
        order=[Card.LINES_BUSY],
        cards={Card.LINES_BUSY: card},
        frequency=Frequency.WEEKLY,
        tz=DUBLIN,
    )
    assert block.title == "Callers who couldn't get through"
    assert [(t.label, t.value) for t in block.tiles] == [
        ("Couldn't get through", "4"),
        ("Put through to your team", "1"),
        ("Left a voicemail", "1"),
    ]
    assert block.note.startswith("Most often Saturday 8–9 pm")
    (empty,) = email_blocks(
        pack=pack,
        order=[Card.LINES_BUSY],
        cards={Card.LINES_BUSY: {**card, "calls": 0, "busiest": []}},
        frequency=Frequency.WEEKLY,
        tz=DUBLIN,
    )
    assert empty.kind == "note"
