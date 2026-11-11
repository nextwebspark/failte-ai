"""The telephony entry point fixes the caller's number before any merge."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

import api.services.pipecat.run_pipeline as run_pipeline_module
from api.services.configuration import ai_model_configuration

MODULE = run_pipeline_module.__name__


async def _contact_phone_for(
    monkeypatch: pytest.MonkeyPatch, call_type: str, initial_context: dict[str, Any]
) -> str | None:
    workflow = SimpleNamespace(
        id=1, organization_id=7, user_id=3, workflow_configurations={}
    )
    run = SimpleNamespace(
        workflow_id=1,
        call_type=call_type,
        initial_context=initial_context,
        definition=SimpleNamespace(workflow_configurations={}),
    )
    monkeypatch.setattr(
        f"{MODULE}.db_client.get_workflow", AsyncMock(return_value=workflow)
    )
    monkeypatch.setattr(
        f"{MODULE}.db_client.get_workflow_run", AsyncMock(return_value=run)
    )
    monkeypatch.setattr(
        ai_model_configuration,
        "get_effective_ai_model_configuration_for_workflow",
        AsyncMock(return_value=SimpleNamespace(is_realtime=False, realtime=None)),
    )
    spec = SimpleNamespace(transport_factory=AsyncMock(return_value=object()))
    monkeypatch.setattr(f"{MODULE}.telephony_registry.get", lambda _: spec)
    monkeypatch.setattr(run_pipeline_module, "create_audio_config", lambda _: None)
    impl = AsyncMock()
    monkeypatch.setattr(run_pipeline_module, "_run_pipeline_impl", impl)

    await run_pipeline_module._run_pipeline_telephony_impl(
        object(),
        provider_name="twilio",
        workflow_id=1,
        workflow_run_id=44,
        organization_id=7,
        call_id="call-1",
        transport_kwargs={},
    )
    assert impl.await_args is not None
    contact_phone: str | None = impl.await_args.kwargs["contact_phone"]
    return contact_phone


@pytest.mark.asyncio
async def test_inbound_calls_pass_the_callers_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = {"caller_number": "+353871234567", "called_number": "+35315550000"}
    assert await _contact_phone_for(monkeypatch, "inbound", context) == "+353871234567"


@pytest.mark.asyncio
async def test_the_run_rows_call_type_wins_over_a_forged_direction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The public API lets initial_context set "direction"; the column decides.
    context = {
        "direction": "inbound",
        "caller_number": "+353871234567",
        "called_number": "+353861111111",
    }
    assert await _contact_phone_for(monkeypatch, "outbound", context) == (
        "+353861111111"
    )


@pytest.mark.asyncio
async def test_a_withheld_number_passes_none(monkeypatch: pytest.MonkeyPatch) -> None:
    context = {"caller_number": "anonymous", "called_number": "+35315550000"}
    assert await _contact_phone_for(monkeypatch, "inbound", context) is None
