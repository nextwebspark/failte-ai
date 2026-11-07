"""Common filter utilities for database queries."""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Float,
    Text,
    and_,
    case,
    cast,
    false,
    func,
    literal,
    not_,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB

from api.db.models import WorkflowRunModel
from api.enums import WORKFLOW_RUN_MODES_BY_CHANNEL, CallType


def get_workflow_run_order_clause(
    sort_by: Optional[str] = None,
    sort_order: str = "desc",
):
    """
    Get the order clause for workflow run queries.

    Args:
        sort_by: Field to sort by ('duration', 'created_at', etc.)
        sort_order: 'asc' or 'desc'

    Returns:
        SQLAlchemy order clause
    """
    # Determine sort column
    if sort_by == "duration":
        sort_column = WorkflowRunModel.usage_info.op("->>")(
            "call_duration_seconds"
        ).cast(Float)
    else:
        # Default to created_at
        sort_column = WorkflowRunModel.created_at

    # Apply sort order
    if sort_order == "asc":
        return sort_column.asc().nullslast()
    else:
        return sort_column.desc().nullslast()


# Mapping of attribute names to database fields
ATTRIBUTE_FIELD_MAPPING = {
    "dateRange": "created_at",
    "dispositionCode": "gathered_context.mapped_call_disposition",
    "duration": "usage_info.call_duration_seconds",
    "status": "is_completed",
    "tokenUsage": "cost_info.total_cost_usd",
    "runId": "id",
    "workflowId": "workflow_id",
    "campaignId": "campaign_id",
    "callTags": "gathered_context.call_tags",
    "callerNumber": "initial_context.caller_number",
    "calledNumber": "initial_context.called_number",
    "callDirection": "call_type",
    "callChannel": "mode",
    "callerSearch": "caller",
    "handledBy": "handled_by",
    "bookingOutcome": "gathered_context.booking_outcome",
    "needsFollowUp": "follow_up",
}

# The stored events that hold what was said: the agent's lines and the
# caller's (final) transcriptions, in ``logs.realtime_feedback_events``.
SPOKEN_EVENT_TYPES = ("rtf-bot-text", "rtf-user-transcription")

# How the engine records a call that was handed to a person (the same rule
# as api/services/reports/daily_report.py's is_transferred): call_status
# "transfer_call" / "call_transferred", or an organization's "XFER" mapping.
_TRANSFERRED_CALL_STATUSES = ("transfer_call", "call_transferred")


def _gathered(key: str):
    """``gathered_context ->> key`` as text, '' when missing."""
    return func.coalesce(
        cast(WorkflowRunModel.gathered_context, JSONB).op("->>")(key), ""
    )


def _initial(key: str):
    return cast(
        cast(WorkflowRunModel.initial_context, JSONB).op("->>")(key),
        Text,
    )


def _passed_to_team():
    return or_(
        _gathered("call_status").in_(_TRANSFERRED_CALL_STATUSES),
        _gathered("mapped_call_disposition") == "XFER",
    )


def search_digits(text: str) -> str:
    """The digits to look for in a stored number: "087 123 4567" and
    "+353 87 123 4567" are stored as "+353871234567", so drop the spacing,
    an international "00" and the leading trunk zero."""
    digits = re.sub(r"\D", "", text)
    if digits.startswith("00"):
        return digits[2:]
    return digits.lstrip("0")


def _escape_like(text: str) -> str:
    """``text`` for a LIKE pattern: its own %, _ and backslash match literally."""
    return re.sub(r"([\\%_])", r"\\\1", text)


def _said_on_call(pattern: str):
    """Whether any line of the conversation (agent or caller) matches the
    ILIKE ``pattern``. Looks only at the spoken text of the stored events,
    not at event types, tool results or timestamps, so "bot" or "2026" don't
    match every call.

    Cost: no index covers this; Postgres reads each candidate row's ``logs``
    and walks its events. The list is always scoped to one organization and,
    by default, to the last 7 days, which keeps the rows scanned small. With
    "Any time" on a large workspace it is a scan of that workspace's calls.
    """
    events = cast(WorkflowRunModel.logs, JSONB).op("->")("realtime_feedback_events")
    # jsonb_array_elements fails on a non-array, so anything else reads as [].
    as_array = case(
        (func.jsonb_typeof(events) == "array", events),
        else_=cast(literal("[]"), JSONB),
    )
    said = func.jsonb_array_elements(as_array).table_valued("value").alias("said")
    line = said.c.value
    return (
        select(literal(1))
        .select_from(said)
        .where(
            line.op("->>")("type").in_(SPOKEN_EVENT_TYPES),
            line.op("->")("payload").op("->>")("text").ilike(pattern, escape="\\"),
        )
        .exists()
    )


def _summary_matches(pattern: str):
    """The post-call review's summary (``annotations.call_review.summary``)."""
    review = cast(WorkflowRunModel.annotations, JSONB).op("->")("call_review")
    return func.coalesce(review.op("->>")("summary"), "").ilike(pattern, escape="\\")


def caller_search(text: str):
    """The one search box (Calls and Follow-ups): the caller's name (as the agent captured it),
    their number (the number the list shows: the caller's on inbound calls
    and the number called on outbound ones), the call's summary, or anything
    said on the call."""
    pattern = f"%{_escape_like(text)}%"
    conditions = [
        _gathered("caller_name").ilike(pattern, escape="\\"),
        _summary_matches(pattern),
        _said_on_call(pattern),
    ]
    digits = search_digits(text)
    if digits:
        conditions.append(
            and_(
                WorkflowRunModel.call_type == CallType.INBOUND.value,
                _initial("caller_number").contains(digits),
            )
        )
        conditions.append(
            and_(
                WorkflowRunModel.call_type != CallType.INBOUND.value,
                _initial("called_number").contains(digits),
            )
        )
    return or_(*conditions)


def apply_workflow_run_filters(
    base_query,
    filters: Optional[List[Dict[str, Any]]] = None,
):
    """
    Apply filters to a workflow run query.

    Supports filtering by:
    - dateRange: Filter by created_at date range
    - dispositionCode: Filter by gathered_context.mapped_call_disposition
    - duration: Filter by usage_info.call_duration_seconds range
    - status: Filter by is_completed status
    - tokenUsage: Filter by cost_info.total_cost_usd range
    - runId: Filter by workflow run ID (exact match)
    - workflowId: Filter by workflow ID (exact match)
    - callTags: Filter by gathered_context.call_tags (array of strings)
    - callerNumber: Filter by initial_context.caller_number (text search)
    - calledNumber: Filter by initial_context.called_number (text search)
    - callDirection: Filter by call_type (inbound / outbound)
    - callChannel: Filter by mode, grouped into telephony / web / chat
    - callerSearch: the caller's captured name or number, the call's summary,
      or what was said on the call (text)
    - needsFollowUp: the calls with an open follow-up. The route resolves
      these with the Follow-ups service and passes the run ids in
      ``value.ids`` (type "runIds"); without resolved ids nothing matches.
    - handledBy: "agent" or "team" (passed to a person), as a radio value
    - bookingOutcome: gathered_context.booking_outcome, any of the codes

    Args:
        base_query: The base SQLAlchemy query to apply filters to
        filters: List of filter dictionaries with structure:
            {"attribute": "filterName", "type": "filterType", "value": {...}}

            Where type is one of:
            - "dateRange": Date range filter with {"from": ..., "to": ...}
            - "multiSelect": Multi-select filter with {"codes": [...]}
            - "numberRange": Number range filter with {"min": ..., "max": ...}
            - "number": Exact number filter with {"value": number}
            - "text": Text search filter with {"value": string}
            - "radio": Radio/status filter with {"status": ...}
            - "tags": Tags filter with {"codes": [...]}

    Returns:
        The query with filters applied
    """

    if not filters:
        return base_query

    filter_conditions = []

    for filter_item in filters:
        attribute = filter_item.get("attribute")
        filter_type = filter_item.get("type")
        value = filter_item.get("value", {})

        # Resolve field from attribute mapping
        field = ATTRIBUTE_FIELD_MAPPING.get(attribute)
        if not field:
            # Skip unknown attributes
            continue

        # Apply the filter based on provided type
        if field and filter_type:
            if filter_type == "number" and field == "id":
                # Filter by exact workflow run ID
                if value.get("value") is not None:
                    filter_conditions.append(WorkflowRunModel.id == value["value"])

            elif filter_type == "number" and field == "workflow_id":
                # Filter by exact workflow ID
                if value.get("value") is not None:
                    filter_conditions.append(
                        WorkflowRunModel.workflow_id == value["value"]
                    )

            elif filter_type == "number" and field == "campaign_id":
                if value.get("value") is not None:
                    filter_conditions.append(
                        WorkflowRunModel.campaign_id == value["value"]
                    )

            elif filter_type == "dateRange" and field == "created_at":
                # Same as attribute-based dateRange
                if value.get("from"):
                    filter_conditions.append(
                        WorkflowRunModel.created_at
                        >= datetime.fromisoformat(value["from"])
                    )
                if value.get("to"):
                    filter_conditions.append(
                        WorkflowRunModel.created_at
                        <= datetime.fromisoformat(value["to"])
                    )

            elif (
                filter_type == "multiSelect"
                and field == "gathered_context.mapped_call_disposition"
            ):
                codes = value.get("codes", [])
                if codes:
                    # Use ->> operator for compatibility with all PostgreSQL versions
                    # (subscript [] only works in PostgreSQL 14+)
                    filter_conditions.append(
                        cast(WorkflowRunModel.gathered_context, JSONB)
                        .op("->>")("mapped_call_disposition")
                        .in_(codes)
                    )

            elif filter_type == "radio" and field == "is_completed":
                status = value.get("status")
                if status == "completed":
                    filter_conditions.append(WorkflowRunModel.is_completed == True)
                elif status == "in_progress":
                    filter_conditions.append(WorkflowRunModel.is_completed == False)

            elif filter_type == "radio" and field == "call_type":
                # RadioValue carries the choice under "status" for every radio
                # filter, not just the completion one.
                direction = value.get("status")
                if direction in {call_type.value for call_type in CallType}:
                    filter_conditions.append(WorkflowRunModel.call_type == direction)

            elif filter_type == "radio" and field == "mode":
                # The UI filters by channel (telephony / web / chat); the column
                # stores the provider-level mode, so expand to that channel's modes.
                modes = WORKFLOW_RUN_MODES_BY_CHANNEL.get(value.get("status"))
                if modes:
                    filter_conditions.append(WorkflowRunModel.mode.in_(modes))

            elif (
                filter_type in ("tags", "multiSelect")
                and field == "gathered_context.call_tags"
            ):
                tags = value.get("codes", [])
                if tags:
                    # The gathered_context column is JSON type (not JSONB)
                    # JSON type doesn't support subscripting, so we must cast to JSONB first
                    # Then extract call_tags and check containment with @>
                    gathered_context_jsonb = cast(
                        WorkflowRunModel.gathered_context, JSONB
                    )
                    # Use -> operator with literal text key to get call_tags as JSONB
                    call_tags = gathered_context_jsonb.op("->")("call_tags")
                    filter_conditions.append(call_tags.op("@>")(func.cast(tags, JSONB)))

            elif filter_type == "text" and field == "initial_context.caller_number":
                phone = value.get("value", "").strip()
                if phone:
                    # Cast ->> result to Text so .contains() emits LIKE,
                    # not the JSONB @> operator (the default for untyped exprs).
                    filter_conditions.append(
                        cast(
                            cast(WorkflowRunModel.initial_context, JSONB).op("->>")(
                                "caller_number"
                            ),
                            Text,
                        ).contains(phone)
                    )

            elif filter_type == "text" and field == "initial_context.called_number":
                phone = value.get("value", "").strip()
                if phone:
                    filter_conditions.append(
                        cast(
                            cast(WorkflowRunModel.initial_context, JSONB).op("->>")(
                                "called_number"
                            ),
                            Text,
                        ).contains(phone)
                    )

            elif filter_type == "text" and field == "caller":
                text = str(value.get("value") or "").strip()
                if text:
                    filter_conditions.append(caller_search(text))

            elif field == "follow_up":
                # Never trust ids from the request: the route replaces this
                # filter's value with the Follow-ups service's open items.
                ids = value.get("ids") if filter_type == "runIds" else None
                run_ids = (
                    [i for i in ids if isinstance(i, int) and not isinstance(i, bool)]
                    if isinstance(ids, list)
                    else []
                )
                filter_conditions.append(
                    WorkflowRunModel.id.in_(run_ids) if run_ids else false()
                )

            elif filter_type == "radio" and field == "handled_by":
                # "agent": the agent dealt with the call itself; "team": it
                # was passed to a person. Anything else matches all.
                who = value.get("status")
                if who == "team":
                    filter_conditions.append(_passed_to_team())
                elif who == "agent":
                    filter_conditions.append(not_(_passed_to_team()))

            elif (
                filter_type == "multiSelect"
                and field == "gathered_context.booking_outcome"
            ):
                outcomes = [
                    str(code).strip().lower()
                    for code in value.get("codes", [])
                    if str(code).strip()
                ]
                if outcomes:
                    filter_conditions.append(
                        func.lower(_gathered("booking_outcome")).in_(outcomes)
                    )

            elif filter_type == "numberRange":
                min_val = value.get("min")
                max_val = value.get("max")

                if field == "usage_info.call_duration_seconds":
                    # Use ->> operator for compatibility with all PostgreSQL versions
                    # (subscript [] only works in PostgreSQL 14+)
                    # Cast to Float, not Integer: some rows store the value as
                    # a JSON float (e.g. 0.0), and Postgres can't cast the text
                    # '0.0' to integer.
                    duration_text = cast(WorkflowRunModel.usage_info, JSONB).op("->>")(
                        "call_duration_seconds"
                    )
                    if min_val is not None:
                        filter_conditions.append(cast(duration_text, Float) >= min_val)
                    if max_val is not None:
                        filter_conditions.append(cast(duration_text, Float) <= max_val)

                elif field == "cost_info.total_cost_usd":
                    # Use ->> operator for compatibility with all PostgreSQL versions
                    cost_text = cast(WorkflowRunModel.cost_info, JSONB).op("->>")(
                        "total_cost_usd"
                    )
                    if min_val is not None:
                        filter_conditions.append(cast(cost_text, Float) >= min_val)
                    if max_val is not None:
                        filter_conditions.append(cast(cost_text, Float) <= max_val)

    if filter_conditions:
        base_query = base_query.where(and_(*filter_conditions))

    return base_query
