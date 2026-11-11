"""The report email built from the cards the owner ticked: which blocks,
in what order, and how they are drawn (tables only). Pure, plus one
fallback check with the loader faked."""

from dataclasses import replace
from datetime import UTC, date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from api.services.dashboard.calls import CallResult, CallView
from api.services.email_reports import content
from api.services.email_reports.cards import email_blocks, reason_colours
from api.services.email_reports.content import build_report
from api.services.email_reports.periods import Frequency, daily_period
from api.services.email_reports.render import Links, render_html, render_text
from api.services.report_cards.catalogue import PACKS, Card, Pack
from api.services.report_cards.layout import StoredLayout, effective_cards

DUBLIN = ZoneInfo("Europe/Dublin")
LINKS = Links(
    dashboard="https://app.example/overview",
    follow_ups="https://app.example/follow-ups",
    manage="https://app.example/settings/reports",
    unsubscribe="https://app.example/reports/unsubscribe/tok",
)
RESTAURANT = PACKS[Pack.RESTAURANT]

CARDS = {
    Card.CALLS_ANSWERED: {
        "calls": 112,
        "previous": 98,
        "change": 14,
        "after_hours": 18,
    },
    Card.BOOKINGS_TAKEN: {
        "count": 38,
        "previous": 32,
        "change": 6,
        "percent_of_calls": 34,
    },
    Card.COVERS_BOOKED: {
        "covers": 142,
        "previous": 121,
        "change": 21,
        "bookings_with_size": 38,
        "not_given": 0,
        "unreadable": 0,
        "average_party": 3.7,
    },
    Card.BOOKINGS_VALUE: {
        "average": Decimal("35"),
        "units": 142,
        "unit": "cover",
        "value": Decimal("4970"),
        "previous_value": Decimal("4235"),
        "change": Decimal("735"),
    },
    Card.CALLERS_WANTED: {
        "unit": "day",
        "series": [
            {"key": "reservations", "label": "Reservations", "count": 56},
            {"key": "questions", "label": "Questions", "count": 24},
            {"key": "other", "label": "Other", "count": 16},
        ],
        "buckets": [],
    },
    Card.UNANSWERED_QUESTIONS: {
        "calls": 4,
        "groups": [
            {
                "question": "Gluten-free <pasta>?",
                "count": 4,
                "run_id": 1,
                "workflow_id": 1,
                "last_asked_at": datetime(2026, 11, 6, tzinfo=UTC),
                "answered": False,
            }
        ],
        "more": 0,
    },
    Card.FOLLOW_UPS: {
        "raised": 3,
        "sorted": 2,
        "open": 1,
        "median_wait_minutes": 20,
        "kinds": [],
    },
    Card.BUSIEST_TIMES: {
        "grid": [[0] * 24] * 7,
        "first_hour": 9,
        "last_hour": 17,
        "max": 0,
        "calls": 112,
        "tip": {
            "weekday": 4,
            "start_hour": 17,
            "end_hour": 19,
            "calls": 19,
            "one_in": 6,
        },
    },
}


def _call(run_id, hour, result=CallResult.HANDLED):
    return CallView(
        run_id=run_id,
        workflow_id=14,
        workflow_name="Linen Quay",
        created_at=datetime(2026, 11, 6, hour, 5, tzinfo=DUBLIN),
        result=result,
        duration_seconds=120,
        has_recording=False,
        caller_number="+353872141234",
        caller_name=None,
        call_reason=None,
        callback_number=None,
        follow_up_mark=None,
    )


def _report(blocks):
    report = build_report(
        business_name="Linen Quay Kitchen",
        agent_name=None,
        period=daily_period(date(2026, 11, 6), DUBLIN, time(18, 0)),
        tz=DUBLIN,
        calls=[_call(1, 9), _call(2, 12, CallResult.BOOKING_MADE)],
        rows=[],
        previous_calls=2,
        follow_up_rows=[],
        open_follow_ups=0,
        agent_status={"answering": True, "reason": None},
        credit=None,
    )
    return replace(report, blocks=tuple(blocks))


def _defaults():
    return [c.key for c in effective_cards(RESTAURANT, StoredLayout()) if c.email]


def test_default_email_keeps_the_old_sections_and_adds_the_packs_numbers():
    order = _defaults()
    blocks = email_blocks(
        pack=RESTAURANT, order=order, cards=CARDS, frequency=Frequency.DAILY, tz=DUBLIN
    )
    assert [b.kind for b in blocks] == [
        "calls",
        "tiles",
        "bars",
        "when",
        "bars",
        "follow_ups",
    ]
    tiles = blocks[1].tiles
    assert [t.label for t in tiles] == ["Bookings taken", "Covers booked"]
    assert tiles[1].value == "142"
    # No average given: the money card was never counted, so it isn't there.
    assert Card.BOOKINGS_VALUE not in order


def test_estimate_says_it_is_one_and_shows_the_formula():
    blocks = email_blocks(
        pack=RESTAURANT,
        order=[Card.BOOKINGS_VALUE],
        cards=CARDS,
        frequency=Frequency.WEEKLY,
        tz=DUBLIN,
    )
    tile = blocks[0].tiles[0]
    assert tile.value == "€4,970"
    assert tile.note == "Estimate: 142 covers × your €35 average spend"
    without = email_blocks(
        pack=RESTAURANT,
        order=[Card.BOOKINGS_VALUE],
        cards={Card.BOOKINGS_VALUE: None},
        frequency=Frequency.WEEKLY,
        tz=DUBLIN,
    )
    assert without == []


def test_owner_order_is_followed_and_unticked_cards_are_left_out():
    order = [Card.UNANSWERED_QUESTIONS, Card.CALLS_ANSWERED]
    blocks = email_blocks(
        pack=RESTAURANT, order=order, cards=CARDS, frequency=Frequency.DAILY, tz=DUBLIN
    )
    assert [b.key for b in blocks] == [Card.UNANSWERED_QUESTIONS, Card.CALLS_ANSWERED]


def test_reason_colours_match_homes_chart():
    assert reason_colours(["reservations", "questions", "other", "not_reviewed"]) == {
        "reservations": "#2a78d6",
        "questions": "#eb6834",
        "other": "#9aa1ad",
        "not_reviewed": "#dfe3e9",
    }


def test_card_email_renders_with_tables_only_and_escapes():
    blocks = email_blocks(
        pack=RESTAURANT,
        order=[*_defaults(), Card.BOOKINGS_VALUE],
        cards=CARDS,
        frequency=Frequency.DAILY,
        tz=DUBLIN,
    )
    report = _report(blocks)
    html = render_html(report, to="owner@example.com", links=LINKS)
    assert "Covers booked" in html and "Average table of 3.7" not in html
    assert "21 more than the same time last week" in html
    assert "Estimate: 142 covers × your €35 average spend" in html
    assert "#2a78d6" in html  # reservations in Home's blue
    assert "Gluten-free &lt;pasta&gt;?" in html and "<pasta>" not in html
    assert "Busiest times" in html and "Friday 5–7 pm takes 1 in 6" in html
    assert "Needs your attention" in html
    assert "<svg" not in html and "<script" not in html and "<img" not in html
    text = render_text(report, to="owner@example.com", links=LINKS)
    assert "Calls: 2" in text
    assert "Covers booked: 142" in text
    assert "- Reservations: 56" in text
    assert "Needs your attention" in text


def test_no_calls_email_is_unchanged_by_cards():
    report = replace(_report([]), calls=0)
    html = render_html(report, to="a@b.ie", links=LINKS)
    assert "No calls today" in html and "Needs your attention" in html


async def test_email_still_goes_in_the_fixed_layout_if_cards_fail(monkeypatch):
    from api.services.report_cards import service

    async def broken(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "report_cards_for", broken)
    blocks = await content._card_blocks(
        9,
        None,
        daily_period(date(2026, 11, 6), DUBLIN, time(18, 0)),
        DUBLIN,
        [],
        datetime(2026, 11, 6, 19, tzinfo=UTC),
    )
    assert blocks is None
