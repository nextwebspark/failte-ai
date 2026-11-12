"""A speech-to-speech agent is told how to say Irish names; a pipeline agent,
whose voice gets respellings instead, is not."""

from unittest.mock import AsyncMock, Mock

import pytest

from api.services.workflow.pipecat_engine import PipecatEngine


def _engine(workflow, *, is_realtime, context=None):
    llm = Mock()
    llm._update_settings = AsyncMock()
    return PipecatEngine(
        workflow=workflow,
        llm=llm,
        call_context_vars=context or {},
        is_realtime=is_realtime,
    )


@pytest.mark.asyncio
async def test_realtime_prompt_gets_the_guide_with_the_callers_name(
    three_node_workflow,
):
    engine = _engine(
        three_node_workflow,
        is_realtime=True,
        context={"caller_name": "Sorcha Ní Bhriain"},
    )
    engine._gathered_context["extracted_variables"] = {"town": "Youghal"}
    agent = engine.active_agent

    await engine._prepare_node(agent, three_node_workflow.nodes["start"])

    prompt = agent.system_prompt
    assert prompt.rstrip().endswith(".")
    assert "# SAYING IRISH NAMES" in prompt
    assert "Aoife = EE-fa" in prompt
    assert "Sorcha = SUR-ka" in prompt
    assert "Ní Bhriain = nee VREE-an" in prompt
    assert "Youghal = YAWL" in prompt
    assert agent.llm._update_settings.call_args.args[0].system_instruction == prompt


@pytest.mark.asyncio
async def test_pipeline_prompt_has_no_guide(three_node_workflow):
    engine = _engine(
        three_node_workflow, is_realtime=False, context={"caller_name": "Aoife"}
    )
    agent = engine.active_agent

    await engine._prepare_node(agent, three_node_workflow.nodes["start"])

    assert "SAYING IRISH NAMES" not in agent.system_prompt
