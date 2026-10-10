"""Agent skills in the engine: per-node selection, the prompt index, the
``load_skill`` / ``read_skill_file`` built-ins and the tool restriction.

Fork-owned. ``PipecatEngine`` holds one :class:`SkillToolManager` per call,
built from the :class:`~api.services.skills.runtime.SkillSet` preloaded at
call start, and calls it from ``_prepare_node``; ``CustomToolManager`` wraps
user tool handlers with :meth:`SkillToolManager.guard`.

Restriction mechanism: a guard in the handlers, not a narrower tool list.
Re-sending a smaller tool list mid-node would change the request prefix that
providers cache (tools come before the conversation) on every load, and the
built-ins would have to re-register mid-turn. Instead the tool list stays
fixed for the node; ``load_skill`` tells the model which tools remain and a
blocked call returns a clear error result. Transition edges, end-call and
transfer tools, the knowledge base and the skill built-ins are never
restricted, so a skill can never trap a caller. The restriction resets on
every node entry (a new :class:`NodeSkillSession`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TYPE_CHECKING, Any

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams

from api.services.skills.runtime import (
    LOAD_SKILL,
    READ_SKILL_FILE,
    NodeSkills,
    NodeSkillSession,
    SkillSet,
    builtin_function_definitions,
    load_skill_result,
    read_skill_file_result,
    skill_load_entry,
)

if TYPE_CHECKING:
    from api.services.workflow.agent_runtime import AgentRuntime
    from api.services.workflow.pipecat_engine import PipecatEngine
    from api.services.workflow.workflow_graph import Node

Handler = Callable[[FunctionCallParams], Awaitable[None]]


class SkillToolManager:
    def __init__(self, engine: PipecatEngine, skill_set: SkillSet) -> None:
        self._engine = engine
        self._skill_set = skill_set
        # Current node's skill state per agent visit.
        self._sessions: dict[str, NodeSkillSession] = {}

    @property
    def skill_set(self) -> SkillSet:
        return self._skill_set

    def session(self, agent: AgentRuntime) -> NodeSkillSession | None:
        return self._sessions.get(agent.visit_id)

    # -- node entry ---------------------------------------------------------

    def enter_node(self, agent: AgentRuntime, node: Node) -> NodeSkills:
        """Start a fresh skill session for ``agent`` on ``node`` (resetting any
        tool restriction) and return the node's skills. Preloaded skills count
        as loaded from the start."""
        node_skills = (
            self._skill_set.for_node(
                getattr(node, "skill_uuids", None),
                getattr(node, "preload_skill_uuids", None),
            )
            if len(self._skill_set)
            else NodeSkills()
        )
        session = NodeSkillSession(node.id, node.name, node_skills)
        self._sessions[agent.visit_id] = session
        for skill in node_skills.preloaded:
            session.record_load(skill)
            # A destination prepared for a transfer may never take the call.
            if agent is self._engine.active_agent:
                self._engine.record_skill_load(
                    skill_load_entry(
                        skill, node_name=node.name, node_id=node.id, via="preload"
                    )
                )
        return node_skills

    def compose_prompt(self, prompt: str, node_skills: NodeSkills) -> str:
        block = node_skills.prompt_block()
        if not block:
            return prompt
        return f"{prompt}\n\n{block}" if prompt else block

    def function_schemas(
        self, node_skills: NodeSkills, existing: list[Any]
    ) -> list[FunctionSchema]:
        """Built-in schemas for the node, skipped (with a warning) if a node
        function already uses a built-in name; saving rejects such workflows,
        but an older one must not send duplicate names to the provider."""
        definitions = builtin_function_definitions(node_skills)
        if not definitions:
            return []
        taken = {str(getattr(f, "name", "")) for f in existing}
        clash = taken.intersection(d.name for d in definitions)
        if clash:
            logger.warning(
                f"Skill built-ins disabled on this node: function name(s) "
                f"{sorted(clash)} already in use"
            )
            return []
        return [
            FunctionSchema(
                name=d.name,
                description=d.description,
                properties=d.properties,
                required=d.required,
            )
            for d in definitions
        ]

    # -- built-ins ------------------------------------------------------------

    def attach(
        self, agent: AgentRuntime, node_skills: NodeSkills, existing: list[Any]
    ) -> list[FunctionSchema]:
        """Register the built-ins for the node and return their schemas
        (none when the node has no skills or a name is already taken)."""
        schemas = self.function_schemas(node_skills, existing)
        if schemas:
            self.register_handlers(agent, node_skills)
        return schemas

    def register_handlers(self, agent: AgentRuntime, node_skills: NodeSkills) -> None:
        if node_skills.is_empty:
            return
        agent.llm.register_function(
            LOAD_SKILL,
            agent.bind_tool(self._engine, self._load_skill_handler(agent)),
        )
        agent.llm.register_function(
            READ_SKILL_FILE,
            agent.bind_tool(self._engine, self._read_skill_file_handler(agent)),
        )

    def _load_skill_handler(self, agent: AgentRuntime) -> Handler:
        async def load_skill(params: FunctionCallParams) -> None:
            session = self._sessions.get(agent.visit_id)
            node_skills = session.skills if session else NodeSkills()
            name = (params.arguments or {}).get("name")
            skill = node_skills.get(name) if isinstance(name, str) else None
            allowed_names = None
            # Mention the restriction only when the node has tools it narrows.
            if session is not None and skill is not None and session.tool_functions:
                allowed_names = session.allowed_function_names(
                    session.restriction_after(skill)
                )
            result, loaded = load_skill_result(
                node_skills, name, allowed_function_names=allowed_names
            )
            if loaded is not None and session is not None:
                session.record_load(loaded)
                self._engine.record_skill_load(
                    skill_load_entry(
                        loaded,
                        node_name=session.node_name,
                        node_id=session.node_id,
                        via=LOAD_SKILL,
                    )
                )
                logger.info(f"Skill loaded: {loaded.name} (node {session.node_name})")
            await params.result_callback(result)

        return load_skill

    def _read_skill_file_handler(self, agent: AgentRuntime) -> Handler:
        async def read_skill_file(params: FunctionCallParams) -> None:
            session = self._sessions.get(agent.visit_id)
            node_skills = session.skills if session else NodeSkills()
            arguments = params.arguments or {}
            await params.result_callback(
                read_skill_file_result(
                    node_skills, arguments.get("name"), arguments.get("path")
                )
            )

        return read_skill_file

    # -- restriction ------------------------------------------------------------

    def guard(
        self,
        agent: AgentRuntime,
        tool_uuid: str,
        function_name: str,
        handler: Handler,
    ) -> Handler:
        """Wrap a restrictable user-tool handler. Returns ``handler`` unchanged
        when the call has no skills."""
        if not len(self._skill_set):
            return handler
        session = self._sessions.get(agent.visit_id)
        if session is not None:
            session.tool_functions[function_name] = tool_uuid

        @wraps(handler)
        async def guarded(params: FunctionCallParams) -> None:
            current = self._sessions.get(agent.visit_id)
            if current is not None and not current.is_tool_allowed(tool_uuid):
                allowed = current.allowed_function_names(current.allowed_tool_uuids)
                logger.info(
                    f"Blocked {function_name}: restricted by loaded skill(s) "
                    f"{list(current.loaded_skill_names)}"
                )
                await params.result_callback(
                    {
                        "error": (
                            f'"{function_name}" is not available while following '
                            f"skill(s) {', '.join(current.loaded_skill_names)}."
                        ),
                        "allowed_tools": allowed or [],
                    }
                )
                return
            await handler(params)

        return guarded
