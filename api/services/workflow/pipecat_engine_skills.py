"""Agent skills in the engine: per-node selection, the prompt index, the
``load_skill`` / ``read_skill_file`` built-ins and the tool restriction.

Fork-owned. ``PipecatEngine`` holds one :class:`SkillToolManager` per call,
built from the :class:`~api.services.skills.runtime.SkillSet` preloaded at
call start (None when the workflow turns skills off), and calls it from
``_prepare_node``; ``CustomToolManager`` wraps user tool handlers with
:meth:`SkillToolManager.guard`.

Node preparation order: :meth:`enter_node` starts a fresh
:class:`NodeSkillSession` (resetting any restriction); user tools are then
registered (their guards bind that session); :meth:`attach` registers the
built-ins unless a node function already uses their names, and only then
applies preloaded skills; :meth:`compose_prompt` renders the block from the
session's final state.

Restriction mechanism: a guard in the handlers, not a narrower tool list.
Re-sending a smaller tool list mid-node would change the request prefix that
providers cache (tools come before the conversation) on every load, and the
built-ins would have to re-register mid-turn. Instead the tool list stays
fixed for the node; ``load_skill`` (or the preloaded section) tells the model
which tools remain and a blocked call returns a clear error result.
Transition edges, end-call and transfer tools, the knowledge base and the
skill built-ins are never restricted, so a skill can never trap a caller.

Handlers bind the session they were registered for, not the visit's current
one: a ``load_skill`` that was in the same tool-call batch as a transition
records against the node it was called on and cannot restrict the next node.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TYPE_CHECKING, Any

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams

from api.db import db_client
from api.services.skills.runtime import (
    LOAD_SKILL,
    READ_SKILL_FILE,
    NodeSkills,
    NodeSkillSession,
    SkillSet,
    builtin_function_definitions,
    load_skill_result,
    load_skill_set,
    read_skill_file_result,
    skill_load_entry,
)

if TYPE_CHECKING:
    from api.services.workflow.agent_runtime import AgentRuntime
    from api.services.workflow.pipecat_engine import PipecatEngine
    from api.services.workflow.workflow_graph import Node

Handler = Callable[[FunctionCallParams], Awaitable[None]]


class SkillToolManager:
    def __init__(self, engine: PipecatEngine, skill_set: SkillSet | None) -> None:
        self._engine = engine
        # None: not loaded (the starting workflow turned skills off).
        self._skill_set = skill_set
        # Current node's skill state per agent visit.
        self._sessions: dict[str, NodeSkillSession] = {}
        # skills_loaded entries of a visit that has not taken the call yet.
        self._pending_log: dict[str, list[dict[str, str]]] = {}

    @property
    def skill_set(self) -> SkillSet | None:
        return self._skill_set

    def session(self, agent: AgentRuntime) -> NodeSkillSession | None:
        return self._sessions.get(agent.visit_id)

    async def prepare_agent(
        self, agent: AgentRuntime, organization_id: int | None
    ) -> None:
        """Before a transfer destination prepares its first node: load the
        skills if the starting workflow had them off and this one has them
        on (call setup of the destination, not a mid-turn hop)."""
        if (
            self._skill_set is None
            and organization_id
            and getattr(agent, "skills_enabled", True)
        ):
            self._skill_set = await load_skill_set(db_client, organization_id)

    # -- node entry ---------------------------------------------------------

    def enter_node(self, agent: AgentRuntime, node: Node) -> NodeSkills:
        """Start a fresh skill session for ``agent`` on ``node`` and return the
        node's skills (empty when skills are off for the call or the agent's
        workflow)."""
        node_skills = NodeSkills()
        if self._skill_set is not None and getattr(agent, "skills_enabled", True):
            node_skills = self._skill_set.for_node(
                getattr(node, "skill_uuids", None),
                getattr(node, "preload_skill_uuids", None),
            )
        self._sessions[agent.visit_id] = NodeSkillSession(
            node.id, node.name, node_skills
        )
        self._pending_log.pop(agent.visit_id, None)
        return node_skills

    def attach(
        self, agent: AgentRuntime, node_skills: NodeSkills, existing: list[Any]
    ) -> list[FunctionSchema]:
        """Register the built-ins for the node, apply preloaded skills and
        return the built-in schemas. Nothing is registered or applied when the
        node has no skills or a node function already uses a built-in name
        (saving rejects such workflows; an older one must not send duplicate
        names to the provider)."""
        session = self._sessions.get(agent.visit_id)
        definitions = builtin_function_definitions(node_skills)
        if session is None or not definitions:
            return []
        taken = {str(getattr(f, "name", "")) for f in existing}
        clash = taken.intersection(d.name for d in definitions)
        if clash:
            logger.warning(
                f"Skill built-ins disabled on node {session.node_name}: function "
                f"name(s) {sorted(clash)} already in use"
            )
            return []
        session.builtins_active = True
        self._register_handlers(agent, session)
        for skill in node_skills.preloaded:
            session.record_load(skill)
            self._log(
                agent,
                skill_load_entry(
                    skill,
                    node_name=session.node_name,
                    node_id=session.node_id,
                    via="preload",
                ),
            )
        return [
            FunctionSchema(
                name=d.name,
                description=d.description,
                properties=d.properties,
                required=d.required,
            )
            for d in definitions
        ]

    def compose_prompt(self, agent: AgentRuntime, prompt: str) -> str:
        session = self._sessions.get(agent.visit_id)
        if session is None:
            return prompt
        preload_allowed: list[str] | None = None
        if session.tool_functions:
            preload_allowed = session.allowed_function_names(session.allowed_tool_uuids)
        block = session.skills.prompt_block(
            with_builtins=session.builtins_active,
            preload_allowed_tools=preload_allowed,
        )
        if not block:
            return prompt
        return f"{prompt}\n\n{block}" if prompt else block

    # -- logging ----------------------------------------------------------------

    def _log(self, agent: AgentRuntime, entry: dict[str, str]) -> None:
        # A destination prepared for a transfer may never take the call: its
        # entries are held until it commits.
        if agent is self._engine.active_agent:
            self._engine.record_skill_load(entry)
        else:
            self._pending_log.setdefault(agent.visit_id, []).append(entry)

    def flush_pending(self, agent: AgentRuntime) -> None:
        """Record a committed transfer destination's held log entries."""
        for entry in self._pending_log.pop(agent.visit_id, []):
            self._engine.record_skill_load(entry)

    # -- built-ins ------------------------------------------------------------

    def _register_handlers(
        self, agent: AgentRuntime, session: NodeSkillSession
    ) -> None:
        agent.llm.register_function(
            LOAD_SKILL,
            agent.bind_tool(self._engine, self._load_skill_handler(agent, session)),
        )
        agent.llm.register_function(
            READ_SKILL_FILE,
            agent.bind_tool(self._engine, self._read_skill_file_handler(session)),
        )

    def _load_skill_handler(
        self, agent: AgentRuntime, session: NodeSkillSession
    ) -> Handler:
        async def load_skill(params: FunctionCallParams) -> None:
            node_skills = session.skills
            name = (params.arguments or {}).get("name")
            skill = node_skills.get(name) if isinstance(name, str) else None
            allowed_names = None
            # Mention the restriction only when the node has tools it narrows.
            if skill is not None and session.tool_functions:
                allowed_names = session.allowed_function_names(
                    session.restriction_after(skill)
                )
            result, loaded = load_skill_result(
                node_skills, name, allowed_function_names=allowed_names
            )
            if loaded is not None:
                session.record_load(loaded)
                self._log(
                    agent,
                    skill_load_entry(
                        loaded,
                        node_name=session.node_name,
                        node_id=session.node_id,
                        via=LOAD_SKILL,
                    ),
                )
                logger.info(f"Skill loaded: {loaded.name} (node {session.node_name})")
            await params.result_callback(result)

        return load_skill

    def _read_skill_file_handler(self, session: NodeSkillSession) -> Handler:
        async def read_skill_file(params: FunctionCallParams) -> None:
            arguments = params.arguments or {}
            await params.result_callback(
                read_skill_file_result(
                    session.skills, arguments.get("name"), arguments.get("path")
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
        """Wrap a restrictable user-tool handler, bound to the agent's current
        node session. Returns ``handler`` unchanged when the node has no
        skills."""
        session = self._sessions.get(agent.visit_id)
        if session is None or session.skills.is_empty:
            return handler
        session.tool_functions[function_name] = tool_uuid

        @wraps(handler)
        async def guarded(params: FunctionCallParams) -> None:
            if not session.is_tool_allowed(tool_uuid):
                allowed = session.allowed_function_names(session.allowed_tool_uuids)
                logger.info(
                    f"Blocked {function_name}: restricted by loaded skill(s) "
                    f"{list(session.loaded_skill_names)}"
                )
                await params.result_callback(
                    {
                        "error": (
                            f'"{function_name}" is not available while following '
                            f"skill(s) {', '.join(session.loaded_skill_names)}."
                        ),
                        "allowed_tools": allowed or [],
                    }
                )
                return
            await handler(params)

        return guarded
