"""Agent skills through ``PipecatEngine``: node preparation (prompt index,
built-in registration), load/read handlers, the tool restriction and its
reset on node change, ``skills_loaded`` logging, and one full pipeline run
with a mock LLM calling ``load_skill``."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMAssistantAggregatorParams,
    LLMContextAggregatorPair,
)
from pipecat.tests.mock_transport import MockTransport
from pipecat.transports.base_transport import TransportParams

from api.db import db_client
from api.db.skill_client import SkillFile
from api.services.skills.runtime import (
    INDEX_HEADER,
    LOAD_SKILL,
    READ_SKILL_FILE,
    RuntimeSkill,
    SkillSet,
)
from api.services.workflow import pipecat_engine as pipecat_engine_module
from api.services.workflow.dto import (
    AgentNodeData,
    EdgeDataDTO,
    EndCallNodeData,
    Position,
    ReactFlowDTO,
    RFEdgeDTO,
    RFNodeDTO,
    StartCallNodeData,
)
from api.services.workflow.pipecat_engine import PipecatEngine
from api.services.workflow.workflow_graph import WorkflowGraph
from api.tests.pipecat_test_utils import run_engine_test_pipeline
from pipecat.tests import MockLLMService, MockTTSService

LOOKUP_UUID = "tool-lookup"
WARRANTY_UUID = "tool-warranty"
END_UUID = "tool-end"
CALC_UUID = "tool-calc"

RETURNS = RuntimeSkill(
    skill_uuid="11111111-1111-1111-1111-111111111111",
    name="returns-policy",
    description="Handle return and refund requests.",
    body_md="RETURNS BODY: ask for the order number.",
    files=(SkillFile(path="references/policy.md", content="30 days."),),
    allowed_tool_uuids=frozenset({LOOKUP_UUID}),
)
BOOKING = RuntimeSkill(
    skill_uuid="22222222-2222-2222-2222-222222222222",
    name="appointment-booking",
    description="Book an appointment.",
    body_md="BOOKING BODY: offer two slots.",
)
MATH = RuntimeSkill(
    skill_uuid="44444444-4444-4444-4444-444444444444",
    name="math",
    description="Arithmetic.",
    body_md="Use the calculator.",
    allowed_tool_uuids=frozenset({CALC_UUID}),
)
SKILLS = SkillSet.of([RETURNS, BOOKING])


def _tool(uuid: str, name: str, category: str) -> SimpleNamespace:
    return SimpleNamespace(
        tool_uuid=uuid,
        name=name,
        description=f"{name} tool",
        category=category,
        definition={"type": category, "config": {"url": "https://x.test"}},
    )


TOOLS = [
    _tool(LOOKUP_UUID, "Lookup Order", "http_api"),
    _tool(WARRANTY_UUID, "Check Warranty", "http_api"),
    _tool(END_UUID, "Hang Up", "end_call"),
    _tool(CALC_UUID, "Calculator", "calculator"),
]


def _workflow(
    *, start: dict[str, Any] | None = None, help_: dict[str, Any] | None = None
) -> WorkflowGraph:
    tool_uuids = [LOOKUP_UUID, WARRANTY_UUID, END_UUID, CALC_UUID]
    return WorkflowGraph(
        ReactFlowDTO(
            nodes=[
                RFNodeDTO(
                    id="start",
                    type="startCall",
                    position=Position(x=0, y=0),
                    data=StartCallNodeData(
                        name="Start",
                        prompt="START PROMPT",
                        add_global_prompt=False,
                        tool_uuids=tool_uuids,
                        **(start or {}),
                    ),
                ),
                RFNodeDTO(
                    id="help",
                    type="agentNode",
                    position=Position(x=0, y=100),
                    data=AgentNodeData(
                        name="Help",
                        prompt="HELP PROMPT",
                        add_global_prompt=False,
                        tool_uuids=tool_uuids,
                        **(help_ or {}),
                    ),
                ),
                RFNodeDTO(
                    id="end",
                    type="endCall",
                    position=Position(x=0, y=200),
                    data=EndCallNodeData(
                        name="End", prompt="END PROMPT", add_global_prompt=False
                    ),
                ),
            ],
            edges=[
                RFEdgeDTO(
                    id="e1",
                    source="start",
                    target="help",
                    data=EdgeDataDTO(label="Get Help", condition="needs help"),
                ),
                RFEdgeDTO(
                    id="e2",
                    source="help",
                    target="end",
                    data=EdgeDataDTO(label="Finish", condition="done"),
                ),
            ],
        )
    )


@pytest.fixture
def patched_db(monkeypatch):
    monkeypatch.setattr(
        db_client,
        "get_organization_id_by_workflow_run_id",
        AsyncMock(return_value=1),
    )
    monkeypatch.setattr(
        db_client,
        "get_tools_by_uuids",
        AsyncMock(
            side_effect=lambda uuids, org: [t for t in TOOLS if t.tool_uuid in uuids]
        ),
    )
    monkeypatch.setattr(
        pipecat_engine_module, "get_disposition_mapping", AsyncMock(return_value={})
    )


class _Harness:
    def __init__(self, workflow: WorkflowGraph, skill_set: SkillSet) -> None:
        self.registered: dict[str, Any] = {}
        llm = MagicMock()
        llm._context = None
        llm._update_settings = AsyncMock()
        llm.register_function = lambda name, fn, **kw: self.registered.__setitem__(
            name, fn
        )
        self.llm = llm
        self.context = LLMContext()
        self.engine = PipecatEngine(
            llm=llm,
            context=self.context,
            workflow=workflow,
            call_context_vars={},
            workflow_run_id=1,
            skill_set=skill_set,
        )
        self._calls = 0

    async def start(self) -> None:
        await self.engine.initialize()
        await self.engine.set_node("start")

    @property
    def system_prompt(self) -> str:
        return self.engine.active_agent.system_prompt

    @property
    def function_names(self) -> list[str]:
        return [f.name for f in self.engine.active_agent.tools.standard_tools]

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        self._calls += 1
        captured: dict[str, Any] = {}

        async def result_callback(result, *, properties=None):
            captured["result"] = result

        params = SimpleNamespace(
            function_name=name,
            tool_call_id=f"call-{self._calls}",
            arguments=arguments,
            result_callback=result_callback,
        )
        await self.registered[name](params)
        return captured["result"]


@pytest.mark.asyncio
async def test_index_only_before_load(patched_db) -> None:
    h = _Harness(_workflow(), SKILLS)
    await h.start()

    assert h.system_prompt.startswith("START PROMPT")
    assert INDEX_HEADER in h.system_prompt
    assert "- returns-policy: Handle return and refund requests." in h.system_prompt
    assert RETURNS.body_md not in h.system_prompt
    assert BOOKING.body_md not in h.system_prompt
    assert LOAD_SKILL in h.function_names and READ_SKILL_FILE in h.function_names
    # The LLM sees the same prompt the agent holds.
    h.llm._update_settings.assert_awaited()
    assert h.context.tools.standard_tools[-1].name == READ_SKILL_FILE


@pytest.mark.asyncio
async def test_load_and_read_through_registered_handlers(patched_db) -> None:
    h = _Harness(_workflow(), SKILLS)
    await h.start()

    loaded = await h.call(LOAD_SKILL, {"name": "returns-policy"})
    assert loaded["instructions"] == RETURNS.body_md
    assert loaded["files"] == ["references/policy.md"]
    assert loaded["allowed_tools"] == ["lookup_order"]

    read = await h.call(
        READ_SKILL_FILE, {"name": "returns-policy", "path": "references/policy.md"}
    )
    assert read["content"] == "30 days."
    traversal = await h.call(
        READ_SKILL_FILE, {"name": "returns-policy", "path": "../policy.md"}
    )
    assert "error" in traversal

    context = await h.engine.get_gathered_context()
    [entry] = context["skills_loaded"]
    assert entry["name"] == "returns-policy"
    assert entry["skill_uuid"] == RETURNS.skill_uuid
    assert entry["node"] == "Start"
    assert entry["via"] == LOAD_SKILL
    assert entry["at"]


@pytest.mark.asyncio
async def test_allowed_tools_restrict_then_reset_on_node_change(patched_db) -> None:
    h = _Harness(_workflow(), SKILLS)
    await h.start()
    # Not restricted before a skill is loaded: the handler would run (we
    # stop short of the HTTP call by checking the guard state instead).
    session = h.engine.skill_tools.session(h.engine.active_agent)
    assert session is not None and session.is_tool_allowed(WARRANTY_UUID)
    # Workflow-control tools are never restrictable.
    assert set(session.tool_functions) == {
        "lookup_order",
        "check_warranty",
        "safe_calculator",
    }

    await h.call(LOAD_SKILL, {"name": "returns-policy"})
    blocked = await h.call("check_warranty", {})
    assert "not available" in blocked["error"]
    assert blocked["allowed_tools"] == ["lookup_order"]
    # The tool list itself is unchanged (no mid-node tool churn).
    assert "check_warranty" in h.function_names

    await h.engine.set_node("help")
    session = h.engine.skill_tools.session(h.engine.active_agent)
    assert session is not None
    assert session.allowed_tool_uuids is None
    assert session.is_tool_allowed(WARRANTY_UUID)


@pytest.mark.asyncio
async def test_narrowing_and_preload(patched_db) -> None:
    h = _Harness(
        _workflow(
            help_={
                "skill_uuids": [BOOKING.skill_uuid],
                "preload_skill_uuids": [RETURNS.skill_uuid],
            }
        ),
        SKILLS,
    )
    await h.start()
    await h.engine.set_node("help")

    prompt = h.system_prompt
    assert prompt.startswith("HELP PROMPT")
    assert RETURNS.body_md in prompt  # inlined
    assert "references/policy.md" in prompt
    assert "- appointment-booking: Book an appointment." in prompt
    assert "- returns-policy:" not in prompt  # preloaded, not indexed
    assert BOOKING.body_md not in prompt

    # A preloaded restricted skill restricts from the start of the node.
    session = h.engine.skill_tools.session(h.engine.active_agent)
    assert session is not None
    assert session.allowed_tool_uuids == frozenset({LOOKUP_UUID})
    context = await h.engine.get_gathered_context()
    assert [(e["name"], e["via"], e["node"]) for e in context["skills_loaded"]] == [
        ("returns-policy", "preload", "Help")
    ]
    # Loading a skill outside the node's selection is refused.
    other = SkillSet.of([*SKILLS.skills])
    assert other.for_node([BOOKING.skill_uuid]).get("warranty") is None
    refused = await h.call(LOAD_SKILL, {"name": "warranty"})
    assert "error" in refused


@pytest.mark.asyncio
async def test_reentering_a_node_does_not_duplicate_the_index(patched_db) -> None:
    h = _Harness(_workflow(), SKILLS)
    await h.start()
    first = h.system_prompt
    await h.engine.set_node("help")
    await h.engine.set_node("start")
    assert h.system_prompt == first
    assert h.system_prompt.count(INDEX_HEADER) == 1


@pytest.mark.asyncio
async def test_no_skills_no_builtins_no_index(patched_db) -> None:
    h = _Harness(_workflow(), SkillSet.empty())
    await h.start()
    assert h.system_prompt == "START PROMPT"
    assert LOAD_SKILL not in h.function_names
    assert LOAD_SKILL not in h.registered
    # User tools are not wrapped when the call has no skills.
    assert h.engine.skill_tools.session(h.engine.active_agent).tool_functions == {}


@pytest.mark.asyncio
async def test_builtins_skipped_when_a_node_function_already_uses_the_name(
    patched_db,
) -> None:
    workflow = _workflow()
    workflow.nodes["start"].out_edges[0].label = "load skill"
    h = _Harness(workflow, SKILLS)
    await h.start()
    assert h.function_names.count(LOAD_SKILL) == 1
    assert READ_SKILL_FILE not in h.function_names


@pytest.mark.asyncio
async def test_mock_llm_calls_load_skill_in_a_running_pipeline(
    simple_workflow: WorkflowGraph,
) -> None:
    """End to end through pipecat: the model calls ``load_skill``; the body
    lands in the conversation as the tool result, never in the prompt."""
    first = MockLLMService.create_multiple_function_call_chunks(
        [
            {
                "name": LOAD_SKILL,
                "arguments": {"name": "returns-policy"},
                "tool_call_id": "call_skill",
            }
        ]
    )
    llm = MockLLMService(
        mock_steps=MockLLMService.create_multi_step_responses(
            first, num_text_steps=1, step_prefix="Response"
        ),
        chunk_delay=0.001,
    )
    transport = MockTransport(
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=16000,
            audio_out_end_silence_secs=0,
        ),
    )
    context = LLMContext()
    aggregator = LLMContextAggregatorPair(
        context, assistant_params=LLMAssistantAggregatorParams()
    ).assistant()
    engine = PipecatEngine(
        llm=llm,
        context=context,
        workflow=simple_workflow,
        call_context_vars={"customer_name": "Test User"},
        workflow_run_id=1,
        skill_set=SKILLS,
    )
    pipeline = Pipeline(
        [
            transport.input(),
            llm,
            MockTTSService(mock_audio_duration_ms=40, frame_delay=0),
            transport.output(),
            aggregator,
        ]
    )
    task = PipelineWorker(pipeline, params=PipelineParams(), enable_rtvi=False)
    engine.call_worker = task

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            db_client,
            "get_organization_id_by_workflow_run_id",
            AsyncMock(return_value=1),
        )
        mp.setattr(
            pipecat_engine_module,
            "get_disposition_mapping",
            AsyncMock(return_value={}),
        )
        # No end_call in this script: the run ends at the timeout.
        await run_engine_test_pipeline(task, engine, transport, timeout=2.0)

    assert INDEX_HEADER in llm._settings.system_instruction
    assert RETURNS.body_md not in llm._settings.system_instruction
    tool_messages = [
        str(m.get("content"))
        for m in context.get_messages()
        if isinstance(m, dict) and m.get("role") == "tool"
    ]
    assert any(RETURNS.body_md in m for m in tool_messages)
    # The node has no user tools, so no restriction note is added.
    assert not any("allowed_tools" in m for m in tool_messages)
    gathered = await engine.get_gathered_context()
    assert [e["name"] for e in gathered["skills_loaded"]] == ["returns-policy"]


@pytest.mark.asyncio
async def test_allowed_tool_still_runs_under_restriction(patched_db) -> None:
    h = _Harness(_workflow(), SkillSet.of([MATH]))
    await h.start()
    loaded = await h.call(LOAD_SKILL, {"name": "math"})
    assert loaded["allowed_tools"] == ["safe_calculator"]
    assert (await h.call("safe_calculator", {"expression": "6 * 7"}))["result"] == 42
    assert "error" in await h.call("lookup_order", {})
