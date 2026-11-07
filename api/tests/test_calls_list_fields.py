"""The Calls list: the stored review's fields on each row, the
"Needs follow-up" filter resolved from Follow-ups, and the CSV headers."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from api.db.organization_usage_client import USAGE_ALLOWED_FILTERS, call_review_fields


def test_review_fields_from_a_stored_review():
    annotations = {
        "call_review": {
            "version": 1,
            "summary": " Booked a table for 4 tonight at 7:00 pm. ",
            "reason": "reservations",
            "reason_label": "Reservations",
            "unanswered_questions": ["Do you have gluten-free pasta?", "", 3],
            "time_was_full": False,
            "model": "x",
            "created_at": "2026-11-06T13:00:00+00:00",
        }
    }
    assert call_review_fields(annotations) == {
        "summary": "Booked a table for 4 tonight at 7:00 pm.",
        "reason_label": "Reservations",
        "unanswered_questions": ["Do you have gluten-free pasta?"],
    }


@pytest.mark.parametrize(
    "annotations",
    [
        None,
        {},
        {"call_review": None},
        {"call_review": "oops"},
        {"call_review": {"summary": 5}},
    ],
)
def test_older_calls_without_a_review_have_empty_fields(annotations):
    assert call_review_fields(annotations) == {
        "summary": None,
        "reason_label": None,
        "unanswered_questions": [],
    }


def test_needs_follow_up_is_an_allowed_list_filter():
    assert "needsFollowUp" in USAGE_ALLOWED_FILTERS


@pytest.mark.asyncio
async def test_needs_follow_up_filter_takes_ids_from_follow_ups(monkeypatch):
    from api.routes.organization_usage import resolve_follow_up_filter
    from api.services.dashboard import service

    asked = {}

    async def open_ids(*, organization_id, workflow_id=None, now=None):
        asked["org"] = organization_id
        return [11, 12]

    monkeypatch.setattr(service, "open_follow_up_run_ids", open_ids)
    other = {"attribute": "callerSearch", "type": "text", "value": {"value": "x"}}
    resolved = await resolve_follow_up_filter(
        3,
        [
            other,
            # Ids sent by the browser are never used.
            {"attribute": "needsFollowUp", "type": "runIds", "value": {"ids": [999]}},
        ],
    )

    assert asked == {"org": 3}
    assert resolved == [
        other,
        {"attribute": "needsFollowUp", "type": "runIds", "value": {"ids": [11, 12]}},
    ]


@pytest.mark.asyncio
async def test_other_filters_skip_the_follow_ups_lookup(monkeypatch):
    from api.routes.organization_usage import resolve_follow_up_filter
    from api.services.dashboard import service

    async def boom(**_):
        raise AssertionError("not needed")

    monkeypatch.setattr(service, "open_follow_up_run_ids", boom)
    filters = [{"attribute": "callerSearch", "type": "text", "value": {"value": "x"}}]
    assert await resolve_follow_up_filter(3, filters) == filters
    assert await resolve_follow_up_filter(3, None) is None


@pytest.mark.asyncio
async def test_open_follow_up_run_ids_matches_the_follow_ups_list(monkeypatch):
    """The ids are the open items Follow-ups shows: done ones are left out."""
    from api.services.dashboard import service
    from api.services.dashboard.calls import CallResult, CallView

    now = datetime(2026, 11, 6, 15, 0, tzinfo=UTC)

    def call(run_id, result, mark=None, caller=None):
        return CallView(
            run_id=run_id,
            workflow_id=14,
            workflow_name="Bia",
            created_at=now,
            result=result,
            duration_seconds=60.0,
            has_recording=True,
            caller_number=caller or f"+35387000000{run_id}",
            caller_name=None,
            call_reason=None,
            callback_number=None,
            follow_up_mark=mark,
        )

    calls = [
        call(1, CallResult.CALLBACK_REQUESTED),
        call(2, CallResult.CALLBACK_REQUESTED, mark={"done_at": now.isoformat()}),
        call(3, CallResult.HANDLED),
        call(4, CallResult.TRANSFER_NOT_ANSWERED),
    ]

    async def load(*_args, **_kwargs):
        return calls

    monkeypatch.setattr(service, "load_calls", load)
    ids = await service.open_follow_up_run_ids(organization_id=3, now=now)
    listed = await service.follow_up_list(
        organization_id=3, status=service.FollowUpStatus.OPEN, workflow_id=None, now=now
    )
    assert ids == [1, 4]
    assert ids == sorted(item["run_id"] for item in listed["items"])


def test_csv_uses_plain_headers():
    from api.services.reports import run_report

    run = SimpleNamespace(
        id=1,
        campaign_id=None,
        workflow_id=2,
        definition_id=None,
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
        initial_context={},
        gathered_context={"mapped_call_disposition": "booking_made"},
        usage_info={"call_duration_seconds": 90},
        cost_info={},
        public_access_token=None,
    )
    header, values = [
        row.split(",")
        for row in run_report.build_run_report_csv([run]).getvalue().splitlines()
    ]
    assert header[0] == "Call ID" and values[0] == "1"
    assert values[header.index("Outcome")] == "booking_made"
    assert "Run ID" not in header and "Call Disposition" not in header


def test_calls_list_reads_a_call_the_way_home_does():
    """A call whose stored ending code is "end_call" ("Call finished") but
    whose calendar confirmed a booking is "booking_made" on the Calls list,
    exactly as Home's recent calls read it; an ordinary call is "handled"."""
    from api.db.organization_usage_client import call_result_of
    from api.services.dashboard.calls import call_result

    now = datetime(2026, 11, 6, 15, 0, tzinfo=UTC)
    booked = {
        "call_tags": ["user_speech"],
        "call_status": "end_call",
        "mapped_call_disposition": "end_call",
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
    ordinary = {
        "call_tags": ["user_speech"],
        "call_status": "end_call",
        "mapped_call_disposition": "end_call",
    }
    for gathered, expected in ((booked, "booking_made"), (ordinary, "handled")):
        run = SimpleNamespace(
            is_completed=True,
            created_at=datetime(2026, 11, 6, 14, 0, tzinfo=UTC),
            gathered_context=gathered,
            usage_info={"call_duration_seconds": 95},
            logs={},
        )
        home = call_result(
            is_completed=True,
            created_at=run.created_at,
            gathered_context=gathered,
            usage_info=run.usage_info,
            logs={},
            now=now,
        )
        assert call_result_of(run, now) == home.value == expected
