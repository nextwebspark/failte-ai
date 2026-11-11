"""The transfer tool rings nobody while the business is closed (structured
opening hours, "pass calls only during opening hours" on) and returns a
not-answered-style result with reason ``closed``; without structured hours
it tries as before."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from api.enums import WorkflowRunMode
from api.schemas.opening_hours import OpeningHours, OpenRange
from api.services.workflow.opening_hours import opening_hours_facts
from api.services.workflow.pipecat_engine_custom_tools import CustomToolManager
from api.tests.test_transfer_message_playback import RecordingEngine, TransferToolModel

MODULE = "api.services.workflow.pipecat_engine_custom_tools"
# Open Tuesday to Sunday 12:00-22:00 in Dublin; closed Monday.
HOURS = OpeningHours(days=((),) + ((OpenRange(open="12:00", close="22:00"),),) * 6)
MONDAY_NOON_UTC = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


async def _run(context, now):
    engine = RecordingEngine()
    engine._call_context_vars = context
    handler = CustomToolManager(engine)._create_transfer_call_handler(
        TransferToolModel(), "transfer_call"
    )
    run = SimpleNamespace(
        mode=WorkflowRunMode.TWILIO.value,
        initial_context={},
        gathered_context={"call_id": "CA1"},
    )
    result_callback = AsyncMock()
    resolve = AsyncMock(side_effect=RuntimeError("tried to ring"))
    with (
        patch(
            f"{MODULE}.db_client.get_workflow_run_by_id", AsyncMock(return_value=run)
        ),
        patch(f"{MODULE}.resolve_transfer_config", resolve),
        patch(
            "api.services.workflow.opening_hours.datetime",
            SimpleNamespace(now=lambda tz=None: now),
        ),
    ):
        await handler(SimpleNamespace(arguments={}, result_callback=result_callback))
    return result_callback.await_args.args[0], resolve


@pytest.mark.asyncio
async def test_closed_rings_nobody():
    result, resolve = await _run(opening_hours_facts(HOURS), MONDAY_NOON_UTC)
    assert result["status"] == "transfer_failed"
    assert result["reason"] == "closed"
    assert "take a message" in result["message"]
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_open_or_no_hours_tries_the_transfer():
    tuesday = datetime(2026, 11, 10, 13, 0, tzinfo=UTC)
    for context, now in (
        (opening_hours_facts(HOURS), tuesday),
        ({}, MONDAY_NOON_UTC),
        (
            opening_hours_facts(
                HOURS.model_copy(update={"transfer_only_when_open": False})
            ),
            MONDAY_NOON_UTC,
        ),
    ):
        result, resolve = await _run(context, now)
        resolve.assert_awaited()
        assert result["reason"] != "closed"
