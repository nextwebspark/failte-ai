"""Skills at call time: the preloaded skill set, per-node selection, the
prompt index and the ``load_skill`` / ``read_skill_file`` built-ins.

Everything here is in-memory and provider-neutral. A call preloads every
active workspace skill once (:func:`load_skill_set`), so loading a skill
mid-turn costs no network hop. The engine glue that registers the built-ins
with the LLM lives in ``api.services.workflow.pipecat_engine_skills``.

Progressive disclosure: a node's system prompt lists only ``name:
description`` for its skills; the body arrives through ``load_skill`` and
reference files through ``read_skill_file`` (exact path match only). A node
may instead *preload* a skill, inlining its body from the start.

Tool restriction: a loaded skill with ``allowed_tool_uuids`` narrows the
node's user tools to those UUIDs (union across loaded restricted skills)
until the node changes. See :class:`NodeSkillSession`.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from loguru import logger

from api.db.skill_client import SkillFile, WorkspaceSkill
from api.services.skills.ports import RuntimeSkillStore

LOAD_SKILL = "load_skill"
READ_SKILL_FILE = "read_skill_file"
# LLM function names owned by the skills runtime. User tools and transition
# edges must not generate these (checked when a workflow is saved).
SKILL_BUILTIN_FUNCTION_NAMES = frozenset({LOAD_SKILL, READ_SKILL_FILE})

SKILLS_LOADED_CONTEXT_KEY = "skills_loaded"

INDEX_HEADER = "Available skills:"
INDEX_INSTRUCTION = (
    f"When a request matches a skill, call {LOAD_SKILL} with its name first "
    "and follow it."
)


@dataclass(frozen=True, slots=True)
class RuntimeSkill:
    """One active workspace skill, as a call sees it."""

    skill_uuid: str
    name: str
    description: str
    body_md: str
    files: tuple[SkillFile, ...] = ()
    # None: no restriction. Otherwise the org tool UUIDs that stay callable
    # once this skill is loaded.
    allowed_tool_uuids: frozenset[str] | None = None

    @classmethod
    def from_workspace(cls, skill: WorkspaceSkill) -> "RuntimeSkill":
        return cls(
            skill_uuid=skill.skill_uuid,
            name=skill.content.name,
            description=skill.content.description,
            body_md=skill.content.body_md,
            files=skill.content.files,
            allowed_tool_uuids=(
                frozenset(skill.allowed_tool_uuids)
                if skill.allowed_tool_uuids is not None
                else None
            ),
        )

    @property
    def file_paths(self) -> list[str]:
        return [f.path for f in self.files]

    def file(self, path: str) -> SkillFile | None:
        for skill_file in self.files:
            if skill_file.path == path:
                return skill_file
        return None


@dataclass(frozen=True, slots=True)
class NodeSkills:
    """The skills one node exposes: ``listed`` in the index (loadable on
    demand) and ``preloaded`` (body already in the prompt)."""

    listed: tuple[RuntimeSkill, ...] = ()
    preloaded: tuple[RuntimeSkill, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.listed and not self.preloaded

    @property
    def names(self) -> list[str]:
        return sorted({s.name for s in (*self.listed, *self.preloaded)})

    def get(self, name: str) -> RuntimeSkill | None:
        for skill in (*self.preloaded, *self.listed):
            if skill.name == name:
                return skill
        return None

    def prompt_block(
        self,
        *,
        with_builtins: bool = True,
        preload_allowed_tools: Sequence[str] | None = None,
    ) -> str:
        """Text appended to the node's system prompt; empty when the node has
        no skills.

        ``with_builtins=False`` (the built-ins could not be registered): no
        index and no file list, only the preloaded bodies.
        ``preload_allowed_tools``: the tool restriction preloaded skills put
        in force, as function names, stated after the preloaded sections.
        """
        parts: list[str] = []
        if self.listed and with_builtins:
            lines = [INDEX_HEADER]
            lines.extend(f"- {s.name}: {s.description}" for s in self.listed)
            lines.append(INDEX_INSTRUCTION)
            parts.append("\n".join(lines))
        for skill in self.preloaded:
            section = f'Skill "{skill.name}" (loaded; follow it):\n{skill.body_md}'
            if skill.files and with_builtins:
                section += f"\nFiles (read with {READ_SKILL_FILE}): " + ", ".join(
                    skill.file_paths
                )
            parts.append(section)
        if self.preloaded and preload_allowed_tools is not None:
            allowed = ", ".join(preload_allowed_tools) or "none"
            parts.append(
                f"Only these tools are available: {allowed} (plus step "
                "transitions and call controls)."
            )
        return "\n\n".join(parts)


@dataclass(frozen=True, slots=True)
class SkillSet:
    """Immutable set of a call's active workspace skills."""

    skills: tuple[RuntimeSkill, ...] = ()
    _by_uuid: Mapping[str, RuntimeSkill] = field(
        default_factory=lambda: MappingProxyType({}), repr=False, compare=False
    )

    @classmethod
    def of(cls, skills: Iterable[RuntimeSkill]) -> "SkillSet":
        ordered = tuple(sorted(skills, key=lambda s: s.name))
        return cls(
            skills=ordered,
            _by_uuid=MappingProxyType({s.skill_uuid: s for s in ordered}),
        )

    @classmethod
    def empty(cls) -> "SkillSet":
        return cls()

    def __len__(self) -> int:
        return len(self.skills)

    def for_node(
        self,
        skill_uuids: Sequence[str] | None,
        preload_skill_uuids: Sequence[str] | None = None,
    ) -> NodeSkills:
        """Select a node's skills.

        ``skill_uuids`` None lists every skill (the default); an explicit empty
        list lists none (the node opts out); otherwise only those. Preloaded
        skills are explicit, inlined and left out of the index. UUIDs that are
        no longer active skills (archived since the workflow was saved) are
        ignored.
        """
        preloaded = tuple(
            self._by_uuid[u] for u in _dedupe(preload_skill_uuids) if u in self._by_uuid
        )
        preloaded_uuids = {s.skill_uuid for s in preloaded}
        if skill_uuids is not None:
            candidates = [
                self._by_uuid[u] for u in _dedupe(skill_uuids) if u in self._by_uuid
            ]
        else:
            candidates = list(self.skills)
        listed = tuple(s for s in candidates if s.skill_uuid not in preloaded_uuids)
        return NodeSkills(listed=listed, preloaded=preloaded)


def _dedupe(values: Sequence[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values or ():
        if isinstance(value, str) and value not in seen:
            seen.add(value)
            out.append(value)
    return out


async def load_skill_set(store: RuntimeSkillStore, organization_id: int) -> SkillSet:
    """Preload a call's skills. A failure yields an empty set: a call must
    never fail because skills could not be read."""
    try:
        rows = await store.list_runtime_skills(organization_id)
    except Exception:  # noqa: BLE001 - degrade to no skills
        logger.exception(
            "Loading skills failed; the call proceeds without skills (org {})",
            organization_id,
        )
        return SkillSet.empty()
    return SkillSet.of(RuntimeSkill.from_workspace(row) for row in rows)


SKILLS_ENABLED_CONFIG_KEY = "skills_enabled"


def skills_enabled(workflow_configurations: Mapping[str, Any] | None) -> bool:
    """The workflow-level switch (``workflow_configurations.skills_enabled``,
    default true). Off: no skills, index or built-ins anywhere in the
    workflow."""
    value = (workflow_configurations or {}).get(SKILLS_ENABLED_CONFIG_KEY)
    return value is not False


async def load_call_skill_set(
    store: RuntimeSkillStore,
    organization_id: int,
    workflow_configurations: Mapping[str, Any] | None,
) -> SkillSet | None:
    """The call's skills, or None (nothing loaded) when the workflow turns
    skills off."""
    if not skills_enabled(workflow_configurations):
        return None
    return await load_skill_set(store, organization_id)


# -- built-in functions ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FunctionDefinition:
    """Provider-neutral function schema (converted by the engine)."""

    name: str
    description: str
    properties: dict[str, Any]
    required: list[str]


def builtin_function_definitions(node: NodeSkills) -> list[FunctionDefinition]:
    """``load_skill`` and ``read_skill_file`` for a node; none when the node
    has no skills."""
    if node.is_empty:
        return []
    names = node.names
    return [
        FunctionDefinition(
            name=LOAD_SKILL,
            description=(
                "Load the full instructions of a listed skill by name. Call it "
                "before handling a request that matches the skill."
            ),
            properties={
                "name": {"type": "string", "enum": names, "description": "Skill name."}
            },
            required=["name"],
        ),
        FunctionDefinition(
            name=READ_SKILL_FILE,
            description=(
                "Read a reference file of a skill. Use only a path listed by "
                f"{LOAD_SKILL} or in the skill's instructions."
            ),
            properties={
                "name": {"type": "string", "enum": names, "description": "Skill name."},
                "path": {
                    "type": "string",
                    "description": "Exact file path, e.g. references/policy.md.",
                },
            },
            required=["name", "path"],
        ),
    ]


def _error(message: str) -> dict[str, Any]:
    return {"error": message}


def _resolve(node: NodeSkills, name: object) -> RuntimeSkill | dict[str, Any]:
    if not isinstance(name, str) or not name:
        return _error("Pass the skill name.")
    skill = node.get(name)
    if skill is None:
        available = ", ".join(node.names) or "none"
        return _error(
            f'No skill named "{name}" is available here. Available: {available}.'
        )
    return skill


def load_skill_result(
    node: NodeSkills, name: object, *, allowed_function_names: Sequence[str] | None
) -> tuple[dict[str, Any], RuntimeSkill | None]:
    """The ``load_skill`` result and the skill loaded (None on error).

    ``allowed_function_names``: when the skill restricts tools, the function
    names that stay callable, so the model is told up front.
    """
    resolved = _resolve(node, name)
    if not isinstance(resolved, RuntimeSkill):
        return resolved, None
    result: dict[str, Any] = {
        "name": resolved.name,
        "instructions": resolved.body_md,
        "files": resolved.file_paths,
    }
    if allowed_function_names is not None:
        result["allowed_tools"] = list(allowed_function_names)
        result["note"] = (
            "While following this skill, only the allowed_tools (plus skill, "
            "transition and end-call functions) can be used in this step."
        )
    return result, resolved


def read_skill_file_result(
    node: NodeSkills, name: object, path: object
) -> dict[str, Any]:
    resolved = _resolve(node, name)
    if not isinstance(resolved, RuntimeSkill):
        return resolved
    if not isinstance(path, str) or not path:
        return _error("Pass the file path.")
    skill_file = resolved.file(path)
    if skill_file is None:
        listed = ", ".join(resolved.file_paths) or "none"
        return _error(f'Skill "{resolved.name}" has no file "{path}". Files: {listed}.')
    return {
        "name": resolved.name,
        "path": skill_file.path,
        "content": skill_file.content,
    }


# -- per-node state -------------------------------------------------------------


class NodeSkillSession:
    """Mutable skill state of one agent visit on one node.

    A new session starts on every node entry, which resets the tool
    restriction. The restriction is the union of ``allowed_tool_uuids`` of the
    loaded skills that set one; a skill without a restriction does not lift
    one that is already in force.
    """

    def __init__(self, node_id: str, node_name: str, skills: NodeSkills) -> None:
        self.node_id = node_id
        self.node_name = node_name
        self.skills = skills
        self._allowed: frozenset[str] | None = None
        self._loaded: list[str] = []
        # LLM function name -> tool UUID for the node's restrictable tools.
        self.tool_functions: dict[str, str] = {}
        # False when the built-ins could not be registered on this node.
        self.builtins_active = False

    @property
    def allowed_tool_uuids(self) -> frozenset[str] | None:
        return self._allowed

    @property
    def loaded_skill_names(self) -> tuple[str, ...]:
        return tuple(self._loaded)

    def restriction_after(self, skill: RuntimeSkill) -> frozenset[str] | None:
        """The restriction that loading ``skill`` would put in force."""
        if skill.allowed_tool_uuids is None:
            return self._allowed
        if self._allowed is None:
            return skill.allowed_tool_uuids
        return self._allowed | skill.allowed_tool_uuids

    def clear_restriction(self) -> None:
        self._allowed = None

    def record_load(self, skill: RuntimeSkill) -> None:
        self._allowed = self.restriction_after(skill)
        if skill.name not in self._loaded:
            self._loaded.append(skill.name)

    def is_tool_allowed(self, tool_uuid: str) -> bool:
        return self._allowed is None or tool_uuid in self._allowed

    def allowed_function_names(
        self, restriction: frozenset[str] | None
    ) -> list[str] | None:
        """The node's restrictable functions left callable under
        ``restriction``; None when nothing is restricted."""
        if restriction is None:
            return None
        return sorted(
            name for name, uuid in self.tool_functions.items() if uuid in restriction
        )


def skill_load_entry(
    skill: RuntimeSkill, *, node_name: str, node_id: str, via: str
) -> dict[str, str]:
    """A ``gathered_context["skills_loaded"]`` record."""
    return {
        "name": skill.name,
        "skill_uuid": skill.skill_uuid,
        "node": node_name,
        "node_id": node_id,
        "via": via,
        "at": datetime.now(UTC).isoformat(),
    }
