"""The demo seed's "Lines were busy" calls have the shape a real turned-away
call is stored with, so Home, Follow-ups and Reports read them the same way.
Pure (no database, no audio)."""

import random
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from api.scripts import seed_demo_accounts as seed
from api.scripts.demo_businesses import RESTAURANT, BusyCall
from api.scripts.demo_chmarine import CHMARINE
from api.services.dashboard.calls import CallResult, call_view
from api.services.dashboard.follow_ups import FollowUpKind, follow_ups
from api.services.workflow.opening_hours import is_open

DUBLIN = ZoneInfo("Europe/Dublin")
# Monday 9 November 2026, 11 am.
NOW = datetime(2026, 11, 9, 11, 0, tzinfo=DUBLIN)


def test_busy_calls_land_on_the_last_such_day_already_past():
    saturday = BusyCall(5, "20:12")
    assert seed.busy_call_time(saturday, NOW) == datetime(
        2026, 11, 7, 20, 12, tzinfo=DUBLIN
    )
    # Saturday morning, before the time: the Saturday before.
    early = datetime(2026, 11, 7, 9, 0, tzinfo=DUBLIN)
    assert seed.busy_call_time(saturday, early) == datetime(
        2026, 10, 31, 20, 12, tzinfo=DUBLIN
    )


def test_restaurant_and_ch_marine_have_saturday_busy_calls_while_open():
    for business in (RESTAURANT, CHMARINE):
        assert business.lines_busy
        for call in business.lines_busy:
            assert call.weekday == 5
            at = seed.busy_call_time(call, NOW)
            assert is_open(business.opening_hours, at)


def _row(run, run_id):
    return {
        "id": run_id,
        "workflow_id": run.workflow_id,
        "workflow_name": "Demo",
        "created_at": run.created_at,
        "is_completed": run.is_completed,
        "has_recording": run_id == 1,
        "gathered_context": run.gathered_context,
        "usage_info": run.usage_info,
        "initial_context": run.initial_context,
        "annotations": run.annotations,
        "transfer_hint": False,
    }


def test_seeded_rows_read_as_lines_busy_follow_ups_and_are_never_billed():
    agent = SimpleNamespace(workflow=SimpleNamespace(id=14))
    caller = RESTAURANT.callers[0]
    start = datetime(2026, 11, 7, 20, 12, tzinfo=UTC)
    runs = [
        seed.busy_call_run(
            RESTAURANT,
            agent,
            call,
            caller,
            start + timedelta(minutes=i),
            voicemail_seconds=11 if call.message else 0,
            rng=random.Random(i),
        )
        for i, call in enumerate(RESTAURANT.lines_busy)
    ]
    views = [
        call_view(_row(run, i + 1), None, start + timedelta(days=2))
        for i, run in enumerate(runs)
    ]
    assert [v.result for v in views] == [CallResult.LINES_BUSY] * len(views)
    assert views[0].lines_busy == "voicemail" and views[0].voicemail_seconds == 11
    assert views[1].lines_busy == "no_message"
    kinds = {i.kind for i in follow_ups(views)}
    assert FollowUpKind.LINES_BUSY in kinds
    for run in runs:
        assert run.usage_info == {}
        assert run.gathered_context["mapped_call_disposition"] == "lines_busy"
        assert run.extra[seed.SEED_MARK]["business"] == RESTAURANT.slug
