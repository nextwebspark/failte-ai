"""Tests for the direction / channel filters used by the usage page."""

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from api.db.filters import apply_workflow_run_filters
from api.db.models import WorkflowRunModel
from api.enums import WORKFLOW_RUN_MODES_BY_CHANNEL, WorkflowRunMode


def _where(filters) -> str:
    query = apply_workflow_run_filters(select(WorkflowRunModel.id), filters)
    sql = str(
        query.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    ).replace("\n", " ")
    return sql[sql.index("WHERE") :] if "WHERE" in sql else ""


def _radio(attribute: str, status: str) -> list[dict]:
    return [{"attribute": attribute, "type": "radio", "value": {"status": status}}]


def test_every_run_mode_belongs_to_exactly_one_channel():
    """An unmapped mode would silently disappear from every channel filter."""
    mapped = [
        mode for modes in WORKFLOW_RUN_MODES_BY_CHANNEL.values() for mode in modes
    ]

    assert {mode.value for mode in WorkflowRunMode} == set(mapped)
    assert len(mapped) == len(set(mapped))


def test_direction_filter_matches_call_type():
    assert _where(_radio("callDirection", "inbound")) == (
        "WHERE workflow_runs.call_type = 'inbound'"
    )
    assert _where(_radio("callDirection", "outbound")) == (
        "WHERE workflow_runs.call_type = 'outbound'"
    )


def test_channel_filter_expands_to_that_channels_modes():
    where = _where(_radio("callChannel", "telephony"))

    assert "workflow_runs.mode IN" in where
    assert "'twilio'" in where
    assert "'smallwebrtc'" not in where
    assert "'textchat'" not in where


def test_channel_and_direction_combine():
    where = _where(
        _radio("callChannel", "telephony") + _radio("callDirection", "outbound")
    )

    assert "workflow_runs.mode IN" in where
    assert "workflow_runs.call_type = 'outbound'" in where


def test_unrecognized_values_do_not_constrain_the_query():
    """'all' means no filter; anything unexpected must not reach the SQL."""
    assert _where(_radio("callDirection", "all")) == ""
    assert _where(_radio("callChannel", "all")) == ""
    assert _where(_radio("callDirection", "'; DROP TABLE workflow_runs;--")) == ""
    assert _where(_radio("callChannel", "voip")) == ""


def _filter(attribute: str, type_: str, value: dict) -> list[dict]:
    return [{"attribute": attribute, "type": type_, "value": value}]


def _params(filters) -> dict:
    query = apply_workflow_run_filters(select(WorkflowRunModel.id), filters)
    return query.compile(dialect=postgresql.dialect()).params


def test_caller_search_matches_name_or_the_number_shown():
    filters = _filter("callerSearch", "text", {"value": "087 123"})
    where = _where(filters)
    values = set(_params(filters).values())

    assert "ILIKE" in where
    assert "%087 123%" in values
    # The number shown: the caller's on inbound calls, the one called otherwise.
    assert "caller_number" in where and "called_number" in where
    assert "87123" in values


def test_caller_search_by_name_escapes_wildcards_and_skips_numbers():
    values = set(
        _params(_filter("callerSearch", "text", {"value": "50%_off"})).values()
    )
    assert r"%50\%\_off%" in values

    where = _where(_filter("callerSearch", "text", {"value": "Murphy"}))
    assert "ILIKE" in where
    assert "caller_number" not in where


def test_caller_search_blank_is_ignored():
    assert _where(_filter("callerSearch", "text", {"value": "  "})) == ""


def test_handled_by_splits_transfers_from_the_rest():
    team = _where(_radio("handledBy", "team"))
    agent = _where(_radio("handledBy", "agent"))

    assert "'transfer_call'" in team and "'call_transferred'" in team
    assert "'XFER'" in team
    assert agent.startswith("WHERE NOT")
    assert _where(_radio("handledBy", "anyone")) == ""


def test_booking_outcome_matches_any_code_case_insensitively():
    where = _where(
        _filter("bookingOutcome", "multiSelect", {"codes": ["Booked", "requested", ""]})
    )

    assert "lower(" in where
    assert "'booked'" in where and "'requested'" in where
    assert _where(_filter("bookingOutcome", "multiSelect", {"codes": []})) == ""


def test_search_digits_drops_spacing_and_trunk_prefixes():
    from api.db.filters import search_digits

    assert search_digits("087 123 4567") == "871234567"
    assert search_digits("+353 87 123") == "35387123"
    assert search_digits("0035387") == "35387"
    assert search_digits("Murphy") == ""
