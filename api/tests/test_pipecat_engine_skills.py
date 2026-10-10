"""Agent skills through ``PipecatEngine``: node preparation (prompt index,
built-in registration), load/read handlers, the tool restriction and its
reset on node change, ``skills_loaded`` logging, and one full pipeline run
with a mock LLM calling ``load_skill``."""

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pipecat.adapters.schemas.function_schema import FunctionSchema
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
from api.services.workflow.pipecat_engine_custom_tools import CustomToolManager
from api.services.workflow.workflow_graph import WorkflowGraph
from api.tests.pipecat_test_utils import run_engine_test_pipeline, stub_agent_runtime
from pipecat.tests import MockLLMService, MockTTSService

LOOKUP_UUID = "tool-lookup"
WARRANTY_UUID = "tool-warranty"
END_UUID = "tool-end"
CALC_UUID = "tool-calc"
TRANSFER_UUID = "tool-transfer"
MCP_UUID = "tool-mcp"

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
    _tool(TRANSFER_UUID, "Transfer Desk", "transfer_call"),
    _tool(MCP_UUID, "Cal", "mcp"),
]


def _workflow(
    *,
    start: dict[str, Any] | None = None,
    help_: dict[str, Any] | None = None,
    tool_uuids: list[str] | None = None,
) -> WorkflowGraph:
    tool_uuids = tool_uuids or [LOOKUP_UUID, WARRANTY_UUID, END_UUID, CALC_UUID]
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
    def __init__(self, workflow: WorkflowGraph, skill_set: SkillSet | None) -> None:
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
        return await self.call_handler(self.registered[name], name, arguments)

    async def call_handler(
        self, handler: Any, name: str, arguments: dict[str, Any]
    ) -> Any:
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
        await handler(params)
        return captured.get("result")


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


# -- review follow-ups ------------------------------------------------------------


@pytest.mark.asyncio
async def test_preloaded_restriction_is_stated_in_the_prompt(patched_db) -> None:
    h = _Harness(_workflow(help_={"preload_skill_uuids": [RETURNS.skill_uuid]}), SKILLS)
    await h.start()
    await h.engine.set_node("help")
    assert h.system_prompt.endswith(
        "Only these tools are available: lookup_order (plus step transitions "
        "and call controls)."
    )
    assert "check_warranty" in h.function_names  # tool list is unchanged


@pytest.mark.asyncio
async def test_explicit_empty_skill_uuids_opts_the_node_out(patched_db) -> None:
    h = _Harness(_workflow(start={"skill_uuids": []}), SKILLS)
    await h.start()
    assert h.system_prompt == "START PROMPT"
    assert LOAD_SKILL not in h.function_names
    await h.engine.set_node("help")  # unset: every skill
    assert INDEX_HEADER in h.system_prompt
    assert LOAD_SKILL in h.function_names


@pytest.mark.asyncio
async def test_workflow_with_skills_disabled_gets_none(patched_db) -> None:
    disabled = _Harness(_workflow(), None)  # nothing loaded for the call
    await disabled.start()
    assert disabled.system_prompt == "START PROMPT"
    assert LOAD_SKILL not in disabled.function_names

    # A visit whose own workflow turns skills off sees none either.
    h = _Harness(_workflow(), SKILLS)
    h.engine.active_agent.skills_enabled = False
    await h.start()
    assert h.system_prompt == "START PROMPT"
    assert LOAD_SKILL not in h.registered


@pytest.mark.asyncio
async def test_load_skill_from_previous_node_cannot_restrict_the_next(
    patched_db,
) -> None:
    """A load_skill in the same tool-call batch as a transition is bound to
    the node it was called on."""
    h = _Harness(_workflow(), SKILLS)
    await h.start()
    stale_load = h.registered[LOAD_SKILL]
    transition = h.registered["get_help"]

    await asyncio.gather(
        h.call_handler(transition, "get_help", {}),
        h.call_handler(stale_load, LOAD_SKILL, {"name": "returns-policy"}),
    )

    assert h.engine.active_agent.current_node.id == "help"
    session = h.engine.skill_tools.session(h.engine.active_agent)
    assert session is not None and session.node_id == "help"
    assert session.allowed_tool_uuids is None
    assert session.loaded_skill_names == ()
    context = await h.engine.get_gathered_context()
    assert [(e["name"], e["node"]) for e in context["skills_loaded"]] == [
        ("returns-policy", "Start")
    ]


@pytest.mark.asyncio
async def test_transfer_destination_preloads_logged_on_commit(patched_db) -> None:
    h = _Harness(_workflow(), SKILLS)
    await h.start()
    destination = stub_agent_runtime(llm=MagicMock(), visit_id="visit-dest")
    destination.workflow = _workflow(
        start={"preload_skill_uuids": [BOOKING.skill_uuid]}
    )
    node = destination.workflow.nodes["start"]

    await h.engine._prepare_node(destination, node, apply_settings=False)
    assert BOOKING.body_md in destination.system_prompt
    context = await h.engine.get_gathered_context()
    assert "skills_loaded" not in context  # not committed yet

    h.engine.skill_tools.flush_pending(destination)
    context = await h.engine.get_gathered_context()
    assert [(e["name"], e["via"]) for e in context["skills_loaded"]] == [
        ("appointment-booking", "preload")
    ]
    h.engine.skill_tools.flush_pending(destination)  # idempotent
    assert len((await h.engine.get_gathered_context())["skills_loaded"]) == 1


@pytest.mark.asyncio
async def test_clash_drops_index_and_preload_restriction(patched_db) -> None:
    workflow = _workflow(start={"preload_skill_uuids": [RETURNS.skill_uuid]})
    workflow.nodes["start"].out_edges[0].label = "load skill"
    h = _Harness(workflow, SKILLS)
    await h.start()
    assert INDEX_HEADER not in h.system_prompt
    assert RETURNS.body_md in h.system_prompt  # body still inlined
    assert "references/policy.md" not in h.system_prompt  # unreadable here
    assert "Only these tools" not in h.system_prompt
    session = h.engine.skill_tools.session(h.engine.active_agent)
    assert session is not None and session.allowed_tool_uuids is None
    assert "skills_loaded" not in await h.engine.get_gathered_context()


@pytest.mark.asyncio
async def test_end_call_and_transfer_still_callable_under_restriction(
    patched_db, monkeypatch
) -> None:
    ran: list[str] = []

    def stub(label: str):
        async def handler(params) -> None:
            ran.append(label)
            await params.result_callback({"status": label})

        return handler

    monkeypatch.setattr(
        CustomToolManager, "_create_end_call_handler", lambda self, t, f: stub("end")
    )
    monkeypatch.setattr(
        CustomToolManager,
        "_create_transfer_call_handler",
        lambda self, t, f: stub("transfer"),
    )
    h = _Harness(
        _workflow(tool_uuids=[LOOKUP_UUID, WARRANTY_UUID, END_UUID, TRANSFER_UUID]),
        SKILLS,
    )
    await h.start()
    await h.call(LOAD_SKILL, {"name": "returns-policy"})
    assert "error" in await h.call("check_warranty", {})
    assert await h.call("hang_up", {}) == {"status": "end"}
    assert await h.call("transfer_desk", {}) == {"status": "transfer"}
    assert ran == ["end", "transfer"]


class _FakeMcpSession:
    available = True
    call_timeout_secs = 5.0

    def function_schemas(self, allowed):
        return [
            FunctionSchema(name=name, description=name, properties={}, required=[])
            for name in ("mcp__cal__book", "mcp__cal__cancel")
        ]

    async def call(self, name, arguments):
        return {"ok": name}


@pytest.mark.asyncio
async def test_mcp_functions_share_their_server_tool_uuid(
    patched_db, monkeypatch
) -> None:
    cal = RuntimeSkill(
        skill_uuid="55555555-5555-5555-5555-555555555555",
        name="calendar",
        description="Book appointments.",
        body_md="Use the calendar.",
        allowed_tool_uuids=frozenset({MCP_UUID}),
    )
    monkeypatch.setattr(PipecatEngine, "_open_mcp_sessions", AsyncMock())
    h = _Harness(
        _workflow(tool_uuids=[LOOKUP_UUID, MCP_UUID]), SkillSet.of([RETURNS, cal])
    )
    h.engine.active_agent.mcp_sessions[MCP_UUID] = _FakeMcpSession()
    await h.start()
    session = h.engine.skill_tools.session(h.engine.active_agent)
    assert session is not None
    assert session.tool_functions == {
        "lookup_order": LOOKUP_UUID,
        "mcp__cal__book": MCP_UUID,
        "mcp__cal__cancel": MCP_UUID,
    }

    loaded = await h.call(LOAD_SKILL, {"name": "calendar"})
    assert loaded["allowed_tools"] == ["mcp__cal__book", "mcp__cal__cancel"]
    assert await h.call("mcp__cal__book", {}) == {"ok": "mcp__cal__book"}
    assert "error" in await h.call("lookup_order", {})

    # Another node visit; a skill restricted to lookup blocks every function
    # of the MCP server.
    await h.engine.set_node("help")
    await h.engine.set_node("start")
    await h.call(LOAD_SKILL, {"name": "returns-policy"})
    for name in ("mcp__cal__book", "mcp__cal__cancel"):
        assert "error" in await h.call(name, {})
