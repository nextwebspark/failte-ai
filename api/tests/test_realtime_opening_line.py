"""The start node's text greeting reaches a speech-to-speech service before it connects."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.services.workflow.pipecat_engine import PipecatEngine


class _RealtimeLLM:
    def __init__(self):
        self.set_opening_line = MagicMock()


def _engine(*, is_realtime: bool, greeting):
    engine = PipecatEngine(
        workflow=None, call_context_vars={}, workflow_run_id=1, is_realtime=is_realtime
    )
    llm = _RealtimeLLM()
    calls: list[str] = []

    async def setup(node):
        calls.append("setup")

    engine._active_agent = SimpleNamespace(llm=llm)
    engine.get_node_greeting = MagicMock(
        side_effect=lambda node_id, agent=None: greeting
    )
    engine._setup_llm_context = AsyncMock(side_effect=setup)
    llm.set_opening_line.side_effect = lambda text: calls.append(f"opening:{text}")
    return engine, llm, calls


@pytest.mark.asyncio
async def test_text_greeting_is_named_before_the_prompt_connects_the_session():
    engine, llm, calls = _engine(is_realtime=True, greeting=("text", "Hello there."))

    await engine._handle_start_node(SimpleNamespace(id="1"))

    assert calls == ["opening:Hello there.", "setup"]


@pytest.mark.asyncio
async def test_audio_or_missing_greeting_clears_the_opening_line():
    for greeting in (("audio", "12"), None):
        engine, llm, calls = _engine(is_realtime=True, greeting=greeting)

        await engine._handle_start_node(SimpleNamespace(id="1"))

        assert calls == ["opening:None", "setup"]


@pytest.mark.asyncio
async def test_pipeline_calls_leave_the_llm_alone():
    engine, llm, calls = _engine(is_realtime=False, greeting=("text", "Hello there."))

    await engine._handle_start_node(SimpleNamespace(id="1"))

    llm.set_opening_line.assert_not_called()
    assert calls == ["setup"]


@pytest.mark.asyncio
async def test_transfer_destination_gets_its_greeting_only_when_it_plays():
    for play_greeting, expected in ((True, ["opening:Hi, sales here."]), (False, [])):
        engine, _llm, calls = _engine(is_realtime=True, greeting=None)
        destination_llm = _RealtimeLLM()
        destination_llm.set_opening_line.side_effect = lambda text: calls.append(
            f"opening:{text}"
        )
        start = SimpleNamespace(id="1")
        destination = SimpleNamespace(
            llm=destination_llm,
            workflow=SimpleNamespace(start_node_id="1", nodes={"1": start}),
        )
        engine.get_node_greeting = MagicMock(
            side_effect=lambda node_id, agent=None: (
                ("text", "Hi, sales here.") if agent is destination else None
            )
        )
        engine._open_mcp_sessions = AsyncMock()
        engine._prepare_node = AsyncMock()

        await engine.prepare_agent(destination, play_greeting=play_greeting)

        assert calls == expected
