"""Emailed reports: period windows, tokens, recipient rules, masking and
rendering. Pure; no database or network."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from api.services.dashboard.calls import CallResult, CallView
from api.services.email_reports import tokens
from api.services.email_reports.content import build_report, callers_wanted
from api.services.email_reports.formatting import (
    change_text,
    daily_since,
    duration_text,
    euro,
    mask_phone,
    period_subtitle,
    period_title,
)
from api.services.email_reports.periods import (
    Frequency,
    daily_period,
    due_to_send,
    latest_due,
    monthly_period,
    preview_period,
    weekly_period,
)
from api.services.email_reports.render import (
    Links,
    render_html,
    render_text,
    report_message,
    subject,
)
from api.services.email_reports.settings import (
    MAX_RECIPIENTS,
    EmailReportSettings,
    RecipientError,
    add_recipient,
    confirm_recipient,
    describe_changes,
    refresh_confirmation,
)

DUBLIN = ZoneInfo("Europe/Dublin")
SIX_PM = time(18, 0)
SECRET = "test-secret-long-enough-for-hs256-ok"


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


# ---------------------------------------------------------------- periods


def test_daily_window_is_the_24_hours_up_to_the_send_time():
    # From 6 pm the day before, so calls after one daily's send time are in
    # the next one (a restaurant's dinner service, a plumber's evening).
    period = daily_period(datetime(2026, 11, 6).date(), DUBLIN, SIX_PM)
    assert period.key == "2026-11-06"
    assert period.start == datetime(2026, 11, 5, 18, 0, tzinfo=DUBLIN)
    assert period.end == period.send_at == datetime(2026, 11, 6, 18, 0, tzinfo=DUBLIN)
    assert period.previous_start == datetime(2026, 10, 29, 18, 0, tzinfo=DUBLIN)
    assert period.previous_end == datetime(2026, 10, 30, 18, 0, tzinfo=DUBLIN)


def test_consecutive_dailies_leave_no_gap():
    friday = daily_period(datetime(2026, 11, 6).date(), DUBLIN, SIX_PM)
    saturday = daily_period(datetime(2026, 11, 7).date(), DUBLIN, SIX_PM)
    assert saturday.start == friday.end


def test_daily_wording_names_the_day_it_is_sent():
    period = daily_period(datetime(2026, 11, 6).date(), DUBLIN, SIX_PM)
    assert period_title(period) == "Friday 6 November"
    assert period_subtitle(period) == "6 pm yesterday to 6 pm today"
    assert daily_since(period) == "since 6 pm yesterday"
    # Sent at midnight, a daily is the whole day before, named after it.
    midnight = daily_period(datetime(2026, 11, 7).date(), DUBLIN, time(0, 0))
    assert period_title(midnight) == "Friday 6 November"
    assert period_subtitle(midnight) == "The whole day"
    assert daily_since(midnight) == "since midnight"


def test_daily_due_only_after_send_time():
    before = utc(2026, 11, 6, 17, 59)  # Dublin is UTC+0 in November
    after = utc(2026, 11, 6, 18, 1)
    assert latest_due(Frequency.DAILY, before, DUBLIN, SIX_PM).key == "2026-11-05"
    assert latest_due(Frequency.DAILY, after, DUBLIN, SIX_PM).key == "2026-11-06"


def test_daily_send_time_follows_summer_time():
    # 18:00 Irish Summer Time is 17:00 UTC.
    assert (
        latest_due(Frequency.DAILY, utc(2026, 7, 1, 17, 1), DUBLIN, SIX_PM).key
        == "2026-07-01"
    )
    assert (
        latest_due(Frequency.DAILY, utc(2026, 7, 1, 16, 59), DUBLIN, SIX_PM).key
        == "2026-06-30"
    )


def test_daily_across_the_clocks_going_back_has_25_hours():
    period = daily_period(datetime(2026, 10, 25).date(), DUBLIN, SIX_PM)
    # Same-zone subtraction is wall-clock in Python; compare in UTC.
    assert period.end.astimezone(UTC) - period.start.astimezone(UTC) == timedelta(
        hours=25
    )


def test_week_the_clocks_go_forward_is_monday_to_monday():
    period = weekly_period(datetime(2026, 3, 23).date(), DUBLIN)
    assert period.key == "2026-W13"
    assert period.end.astimezone(UTC) - period.start.astimezone(UTC) == timedelta(
        days=7, hours=-1
    )
    assert period.send_at == datetime(2026, 3, 30, 8, 0, tzinfo=DUBLIN)


def test_weekly_due_monday_8am_covering_last_week():
    monday_9 = utc(2026, 11, 9, 9, 0)
    period = latest_due(Frequency.WEEKLY, monday_9, DUBLIN, SIX_PM)
    assert period.start == datetime(2026, 11, 2, tzinfo=DUBLIN)
    assert period.end == datetime(2026, 11, 9, tzinfo=DUBLIN)
    monday_7 = utc(2026, 11, 9, 7, 0)
    assert latest_due(Frequency.WEEKLY, monday_7, DUBLIN, SIX_PM).start == datetime(
        2026, 10, 26, tzinfo=DUBLIN
    )


@pytest.mark.parametrize(
    ("first", "key", "days"),
    [
        ("2026-02-01", "2026-02", 28),
        ("2028-02-01", "2028-02", 29),
        ("2026-12-01", "2026-12", 31),
    ],
)
def test_month_windows(first, key, days):
    period = monthly_period(datetime.fromisoformat(first).date(), DUBLIN)
    assert period.key == key
    assert (period.end.date() - period.start.date()).days == days


def test_monthly_due_on_the_first_at_8am_and_year_wraps():
    period = latest_due(Frequency.MONTHLY, utc(2027, 1, 1, 8, 30), DUBLIN, SIX_PM)
    assert period.key == "2026-12"
    assert period.previous_start == datetime(2026, 11, 1, tzinfo=DUBLIN)
    assert (
        latest_due(Frequency.MONTHLY, utc(2027, 1, 1, 7, 0), DUBLIN, SIX_PM).key
        == "2026-11"
    )


def test_other_zone_is_respected():
    new_york = ZoneInfo("America/New_York")
    # 18:00 in New York on 6 Nov is 23:00 UTC.
    assert (
        latest_due(Frequency.DAILY, utc(2026, 11, 6, 22, 0), new_york, SIX_PM).key
        == "2026-11-05"
    )
    assert (
        latest_due(Frequency.DAILY, utc(2026, 11, 6, 23, 1), new_york, SIX_PM).key
        == "2026-11-06"
    )


def test_due_once_per_period_and_not_stale():
    now = utc(2026, 11, 6, 18, 16)
    period = due_to_send(Frequency.DAILY, now, DUBLIN, SIX_PM, None)
    assert period is not None and period.key == "2026-11-06"
    # The claim stored the key: the next pass (or a second worker) sends nothing.
    assert due_to_send(Frequency.DAILY, now, DUBLIN, SIX_PM, "2026-11-06") is None
    assert (
        due_to_send(
            Frequency.DAILY, now + timedelta(minutes=15), DUBLIN, SIX_PM, "2026-11-06"
        )
        is None
    )
    # The worker was down all night: yesterday's report is too stale to send.
    assert (
        due_to_send(
            Frequency.DAILY, utc(2026, 11, 7, 9, 0), DUBLIN, SIX_PM, "2026-11-05"
        )
        is None
    )


def test_week_keys_sort_in_time_order_across_years():
    assert weekly_period(datetime(2027, 1, 4).date(), DUBLIN).key > "2026-W53"
    late_dec = weekly_period(datetime(2026, 12, 28).date(), DUBLIN)
    assert late_dec.key == "2026-W53"


def test_preview_before_send_time_is_today_so_far():
    now = utc(2026, 11, 6, 11, 0)
    period = preview_period(Frequency.DAILY, now, DUBLIN, SIX_PM)
    assert period.key == "2026-11-06" and not period.complete
    assert period.end == now
    assert period.previous_end - period.previous_start == now - period.start


# ----------------------------------------------------------------- tokens


def test_confirm_token_round_trip_and_audience():
    token = tokens.confirm_token(
        organization_id=7,
        recipient_id="r1",
        address="Ann@Example.ie",
        nonce="n1",
        secret=SECRET,
    )
    claim = tokens.read_confirm_token(token, SECRET)
    assert (
        claim is not None and claim.organization_id == 7 and claim.recipient_id == "r1"
    )
    assert claim.matches("ann@example.ie", "n1")
    assert not claim.matches("ann@example.ie", "other")
    assert not claim.matches("bob@example.ie", "n1")
    # Not usable as an unsubscribe token, nor under another secret.
    assert tokens.read_unsubscribe_token(token, SECRET) is None
    assert (
        tokens.read_confirm_token(token, "other-secret-long-enough-for-hs256-ok")
        is None
    )


def test_confirm_token_expires_after_48_hours():
    issued = datetime.now(UTC) - timedelta(hours=49)
    token = tokens.confirm_token(
        organization_id=7,
        recipient_id="r1",
        address="a@b.ie",
        nonce="n",
        secret=SECRET,
        now=issued,
    )
    assert tokens.read_confirm_token(token, SECRET) is None


def test_tampered_token_is_rejected():
    token = tokens.unsubscribe_token(
        organization_id=7, recipient_id="r1", address="a@b.ie", secret=SECRET
    )
    head, body, sig = token.split(".")
    assert tokens.read_unsubscribe_token(f"{head}.{body}x.{sig}", SECRET) is None
    assert tokens.read_unsubscribe_token(token, SECRET) is not None


def test_token_does_not_carry_the_address():
    token = tokens.unsubscribe_token(
        organization_id=7, recipient_id="r1", address="ann@example.ie", secret=SECRET
    )
    import base64

    body = token.split(".")[1]
    decoded = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()
    assert "ann" not in decoded and "example" not in decoded


# ------------------------------------------------------------- recipients

NOW = utc(2026, 11, 6, 12, 0)


def test_own_verified_email_is_active_at_once():
    settings = EmailReportSettings()
    r = add_recipient(
        settings,
        address="Owner@Bia.ie",
        by_user_id=1,
        own_verified_email="owner@bia.ie",
        now=NOW,
    )
    assert (
        r.status == "active" and r.verified_via == "account" and r.confirm_nonce is None
    )


def test_other_address_waits_for_its_link_which_works_once():
    settings = EmailReportSettings()
    r = add_recipient(
        settings,
        address="chef@bia.ie",
        by_user_id=1,
        own_verified_email="owner@bia.ie",
        now=NOW,
    )
    assert r.status == "pending" and r.confirm_nonce
    assert settings.active_recipients() == []
    nonce = r.confirm_nonce

    def matches(recipient, n):
        return recipient.email == "chef@bia.ie" and (n is None or n == nonce)

    assert (
        confirm_recipient(settings, r.id, email_matches=matches, now=NOW) == "confirmed"
    )
    assert settings.active_recipients()[0].email == "chef@bia.ie"
    assert settings.find(r.id).confirm_nonce is None
    assert (
        confirm_recipient(settings, r.id, email_matches=matches, now=NOW) == "already"
    )


def test_wrong_link_does_not_confirm():
    settings = EmailReportSettings()
    r = add_recipient(
        settings, address="chef@bia.ie", by_user_id=1, own_verified_email=None, now=NOW
    )
    assert (
        confirm_recipient(settings, r.id, email_matches=lambda *_: False, now=NOW)
        == "invalid"
    )
    assert (
        confirm_recipient(settings, "nope", email_matches=lambda *_: True, now=NOW)
        == "invalid"
    )
    assert settings.find(r.id).status == "pending"


def test_resend_replaces_the_link_but_not_too_often():
    settings = EmailReportSettings()
    r = add_recipient(
        settings, address="chef@bia.ie", by_user_id=1, own_verified_email=None, now=NOW
    )
    first = r.confirm_nonce
    with pytest.raises(RecipientError):
        refresh_confirmation(settings, r.id, NOW + timedelta(seconds=30))
    refreshed = refresh_confirmation(settings, r.id, NOW + timedelta(minutes=3))
    assert refreshed.confirm_nonce != first


def test_duplicates_and_limit():
    settings = EmailReportSettings()
    add_recipient(
        settings, address="a@bia.ie", by_user_id=1, own_verified_email=None, now=NOW
    )
    with pytest.raises(RecipientError):
        add_recipient(
            settings,
            address=" A@BIA.ie ",
            by_user_id=1,
            own_verified_email=None,
            now=NOW,
        )
    for i in range(MAX_RECIPIENTS - 1):
        add_recipient(
            settings,
            address=f"x{i}@bia.ie",
            by_user_id=1,
            own_verified_email=None,
            now=NOW,
        )
    with pytest.raises(RecipientError):
        add_recipient(
            settings,
            address="late@bia.ie",
            by_user_id=1,
            own_verified_email=None,
            now=NOW,
        )


def test_changes_are_described_for_the_history():
    before = EmailReportSettings()
    after = before.model_copy(update={"daily": True, "daily_send_time": "17:30"})
    assert describe_changes(before, after) == [
        "daily report on",
        "daily time 18:00 -> 17:30",
    ]


# ------------------------------------------------------------- formatting


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("+353872141234", "087 214 xxxx"),
        ("087 214 1234", "087 214 xxxx"),
        ("+35312345678", "01 234 xxxx"),
        ("+353613301234", "061 330 xxxx"),
        ("+447700900123", "+44 7700 90xxxx"),
        ("anonymous", "Number withheld"),
        (None, "Number withheld"),
    ],
)
def test_phone_numbers_are_masked(raw, shown):
    assert mask_phone(raw) == shown


def test_wording():
    assert duration_text(134) == "2 min 14 s"
    assert duration_text(48) == "48 s"
    assert euro(12.4) == "€12.40"
    assert change_text(4, Frequency.DAILY) == "4 more than the same time last week"
    assert change_text(-2, Frequency.MONTHLY) == "2 fewer than the month before"
    assert change_text(None, Frequency.DAILY) is None
    assert (
        period_title(weekly_period(datetime(2026, 10, 26).date(), DUBLIN))
        == "26 Oct – 1 Nov"
    )


# ---------------------------------------------------------------- render


def _call(
    run_id,
    hour,
    result=CallResult.HANDLED,
    name=None,
    number="+353872141234",
    reason=None,
):
    return CallView(
        run_id=run_id,
        workflow_id=14,
        workflow_name="Bia",
        created_at=datetime(2026, 11, 6, hour, 5, tzinfo=DUBLIN),
        result=result,
        duration_seconds=120,
        has_recording=False,
        caller_number=number,
        caller_name=name,
        call_reason=reason,
        callback_number=None,
        follow_up_mark=None,
    )


LINKS = Links(
    dashboard="https://app.example/overview",
    follow_ups="https://app.example/follow-ups",
    manage="https://app.example/settings/reports",
    unsubscribe="https://app.example/reports/unsubscribe/tok",
    one_click="https://api.example/api/v1/public/email-reports/unsubscribe/tok",
)


def _report(calls, rows=(), status=None, follow_ups=()):
    return build_report(
        business_name="Bia <Bistro>",
        agent_name=None,
        period=daily_period(datetime(2026, 11, 6).date(), DUBLIN, SIX_PM),
        tz=DUBLIN,
        calls=calls,
        rows=rows,
        previous_calls=2,
        follow_up_rows=list(follow_ups),
        open_follow_ups=len(follow_ups),
        agent_status=status or {"answering": True, "reason": None},
        credit={"spendable_eur": 12.4, "minutes_left": 50, "running_low": False},
    )


def test_callers_wanted_reads_reviews_only():
    rows = [
        {"annotations": {"call_review": {"reason_label": "Booking a table"}}},
        {"annotations": {"call_review": {"reason_label": "Booking a table"}}},
        {"annotations": {"call_review": {"reason_label": "Opening hours"}}},
        {"annotations": {}},
        {"annotations": {"call_review": "broken"}},
    ]
    bars = callers_wanted(rows)
    assert [(b.label, b.count) for b in bars] == [
        ("Booking a table", 2),
        ("Opening hours", 1),
    ]


def test_report_email_has_the_numbers_masked_and_escaped():
    calls = [
        _call(1, 9),
        _call(2, 12, CallResult.BOOKING_MADE),
        _call(3, 13, CallResult.PASSED_TO_TEAM),
        _call(4, 14, CallResult.HUNG_UP_SILENT),
        _call(5, 15, CallResult.CALLBACK_REQUESTED, name="Mary"),
    ]
    follow_ups = [
        {
            "caller_name": "Mary",
            "caller_number": "+353872141234",
            "callback_number": None,
            "call_reason": "Large party on Saturday",
            "kind": "callback",
            "created_at": datetime(2026, 11, 6, 15, 5, tzinfo=DUBLIN),
        },
        {
            "caller_name": None,
            "caller_number": "+353861112222",
            "callback_number": None,
            "call_reason": None,
            "kind": "repeat_caller",
            "created_at": datetime(2026, 11, 6, 16, 0, tzinfo=DUBLIN),
        },
    ]
    rows = [{"annotations": {"call_review": {"reason_label": "Booking a table"}}}]
    report = _report(calls, rows, follow_ups=follow_ups)
    assert report.calls == 5 and report.handled == 2 and report.bookings == 1
    assert (
        subject(report)
        == "Bia <Bistro> · Friday 6 November: 5 calls, 2 handled by your agent"
    )
    html = render_html(report, to="owner@bia.ie", links=LINKS)
    assert "Bia &lt;Bistro&gt;" in html and "<Bistro>" not in html
    assert "087 214 xxxx" in html and "2141234" not in html
    assert "086 111 xxxx" in html
    assert "Large party on Saturday" in html
    assert "What callers wanted" in html and "Booking a table" in html
    assert "When people called" in html
    assert "€12.40 left" in html
    assert "https://app.example/overview" in html
    assert "Unsubscribe" in html and "reports/unsubscribe/tok" in html
    assert "<svg" not in html and "<script" not in html
    text = render_text(report, to="owner@bia.ie", links=LINKS)
    assert "Calls: 5" in text and "2141234" not in text and "Unsubscribe:" in text


def test_report_without_reviews_or_credit_leaves_those_out():
    from dataclasses import replace

    report = replace(_report([_call(1, 9)]), credit=None)
    html = render_html(report, to="a@b.ie", links=LINKS)
    assert "What callers wanted" not in html
    assert "Call credit" not in html


def test_quiet_day_still_sends_and_says_why():
    report = _report([])
    assert subject(report) == "Bia <Bistro> · Friday 6 November: no calls"
    html = render_html(report, to="a@b.ie", links=LINKS)
    assert "No calls since the last report" in html and "just been quiet" in html
    assert "Nobody has rung since 6 pm yesterday." in html
    off = _report([], status={"answering": False, "reason": "number_off"})
    html_off = render_html(off, to="a@b.ie", links=LINKS)
    assert "phone number is switched off" in html_off
    assert "just been quiet" not in html_off


def test_message_carries_one_click_unsubscribe_headers():
    message = report_message(_report([_call(1, 9)]), to="a@b.ie", links=LINKS)
    headers = dict(message.headers)
    assert headers["List-Unsubscribe"] == f"<{LINKS.one_click}>"
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert message.text and message.html


def test_smtp_keeps_a_long_list_unsubscribe_header_readable():
    from email import policy
    from email.message import EmailMessage as Mime

    from api.services.email.smtp_sender import _LONG_HEADERS

    url = (
        "<https://api.example/api/v1/public/email-reports/unsubscribe/"
        + "a" * 300
        + ">"
    )
    mime = Mime(policy=_LONG_HEADERS)
    mime["List-Unsubscribe"] = url
    mime.set_content("x")
    assert url in mime.as_string()
    assert policy.default.max_line_length == 78


def test_a_test_email_has_no_unsubscribe_link():
    from dataclasses import replace

    links = replace(LINKS, unsubscribe=LINKS.manage, one_click=None, why="A test.")
    message = report_message(_report([_call(1, 9)]), to="a@b.ie", links=links)
    assert "Unsubscribe" not in message.html and "Unsubscribe" not in message.text
    assert "A test." in message.html and message.headers == ()


def test_report_counts_calls_outside_opening_hours_when_set():
    from api.schemas.opening_hours import OpeningHours, OpenRange
    from api.services.workflow.opening_hours import opening_hours_facts

    # Bia (agent 14) is open 12:00-15:00 every day.
    hours = OpeningHours(days=((OpenRange(open="12:00", close="15:00"),),) * 7)
    agent = {
        "id": 14,
        "name": "Bia",
        "status": "active",
        "opening_hours_schedule": opening_hours_facts(hours)["opening_hours_schedule"],
    }
    calls = [_call(1, 9), _call(2, 12), _call(3, 16)]
    report = build_report(
        business_name="Bia",
        agent_name=None,
        period=daily_period(datetime(2026, 11, 6).date(), DUBLIN, SIX_PM),
        tz=DUBLIN,
        calls=calls,
        rows=(),
        previous_calls=0,
        follow_up_rows=[],
        open_follow_ups=0,
        agent_status={"answering": True, "reason": None},
        credit=None,
        agents=[agent],
    )
    assert report.after_hours == 2
    assert "Outside opening hours: 2" in render_text(report, to="o@bia.ie", links=LINKS)
    assert "Outside opening hours: <strong>2</strong>" in render_html(
        report, to="o@bia.ie", links=LINKS
    )
    # Without hours set as times the line is left out.
    plain = _report(calls)
    assert plain.after_hours is None
    assert "Outside opening hours" not in render_text(plain, to="o@bia.ie", links=LINKS)
