"""The demo seed's call history agrees with each business's opening hours:
with "only during opening hours" on, no seeded call puts anyone through while
the business is closed; such calls get the live gate's closed skip instead.
Pure (no database)."""

import random
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from api.scripts import demo_businesses as d
from api.services.workflow.opening_hours import is_open

NOW = datetime(2026, 11, 7, 15, 0, tzinfo=ZoneInfo("Europe/Dublin"))


def _seeded_plans(business):
    """Each call as seed_calls plans it (same random streams)."""
    for index, start in enumerate(d.call_dates(business, NOW)):
        rng = random.Random(f"{business.slug}:call:{index}")
        pool = business.callers
        caller = rng.choice(pool[:8]) if rng.random() < 0.3 else rng.choice(pool)
        ctx = d.Ctx(
            rng=rng, caller=caller, started=start, business=business, greeting="Hi"
        )
        weights = [w for w, _ in business.scenarios]
        scenario = rng.choices([s for _, s in business.scenarios], weights)[0]
        yield start, d.fit_to_opening_hours(scenario(ctx), ctx)


@pytest.mark.parametrize("business", d.BUSINESSES, ids=lambda b: b.slug)
def test_transfers_only_while_open(business):
    hours = business.opening_hours
    assert hours is not None
    plans = list(_seeded_plans(business))
    after_hours = [(s, p) for s, p in plans if not is_open(hours, s)]
    # A realistic share comes in while closed.
    assert 0.05 <= len(after_hours) / len(plans) <= 0.5
    for start, plan in plans:
        transfers = [s for s in plan.steps if s.kind == "transfer"]
        if not hours.transfer_only_when_open:
            assert not any(s.closed for s in transfers)
            continue
        if is_open(hours, start):
            assert not any(s.closed for s in transfers)
        else:
            assert all(s.closed for s in transfers)
            assert plan.outcome not in (d.TRANSFERRED, d.TRANSFER_NOT_ANSWERED)
            if transfers:
                assert plan.outcome in (d.CALLBACK, d.HANDLED)
                assert plan.status == "end_call"


def test_some_calls_get_the_closed_skip():
    skipped = [
        plan
        for business in d.BUSINESSES
        for _, plan in _seeded_plans(business)
        if any(s.closed for s in plan.steps)
    ]
    assert skipped
    assert {p.outcome for p in skipped} <= {d.CALLBACK, d.HANDLED}
