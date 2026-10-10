"""Save-time checks for agent skills in a workflow definition.

Fork-owned; called from ``validate_workflow_tool_name_collisions`` so every
save path (UI routes, MCP create/save) runs it.

- ``skill_uuids`` / ``preload_skill_uuids`` must name active skills of the
  saving organization (a foreign or archived UUID is rejected, never
  silently dropped).
- Transition edges must not generate a skill built-in function name
  (``load_skill``, ``read_skill_file``); custom tools are checked alongside
  the other custom-tool name rules.
"""

from typing import Any

from api.services.skills.ports import SkillDirectory
from api.services.skills.runtime import SKILL_BUILTIN_FUNCTION_NAMES
from api.services.workflow.errors import ItemKind, WorkflowError
from api.services.workflow.workflow_graph import transition_tool_name

SKILL_REF_FIELDS = ("skill_uuids", "preload_skill_uuids")


def _skill_refs_by_node(
    nodes: list[Any],
) -> dict[tuple[str, str], list[str]]:
    refs: dict[tuple[str, str], list[str]] = {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str):
            continue
        data = node.get("data")
        if not isinstance(data, dict):
            continue
        for field in SKILL_REF_FIELDS:
            raw = data.get(field)
            if isinstance(raw, list):
                values = [u for u in raw if isinstance(u, str)]
                if values:
                    refs[(node["id"], field)] = values
    return refs


async def validate_workflow_skill_refs(
    workflow_definition: dict[str, Any] | None,
    organization_id: int,
    directory: SkillDirectory,
) -> list[WorkflowError]:
    if not workflow_definition:
        return []
    nodes = workflow_definition.get("nodes")
    if not isinstance(nodes, list):
        return []
    refs = _skill_refs_by_node(nodes)
    if not refs:
        return []
    wanted = {u for values in refs.values() for u in values}
    active = await directory.find_active_skill_uuids(organization_id, wanted)
    errors: list[WorkflowError] = []
    for (node_id, field), values in refs.items():
        missing = [u for u in dict.fromkeys(values) if u not in active]
        if missing:
            errors.append(
                WorkflowError(
                    kind=ItemKind.node,
                    id=node_id,
                    field=f"data.{field}",
                    message=(
                        "Unknown or archived skill(s) for this workspace: "
                        + ", ".join(missing)
                    ),
                )
            )
    return errors


def reserved_transition_name_errors(
    workflow_definition: dict[str, Any] | None,
) -> list[WorkflowError]:
    if not workflow_definition:
        return []
    edges = workflow_definition.get("edges")
    if not isinstance(edges, list):
        return []
    errors: list[WorkflowError] = []
    for edge in edges:
        if not isinstance(edge, dict) or not isinstance(edge.get("id"), str):
            continue
        data = edge.get("data")
        label = data.get("label") if isinstance(data, dict) else None
        if not isinstance(label, str) or not label:
            continue
        function_name = transition_tool_name(label)
        if function_name in SKILL_BUILTIN_FUNCTION_NAMES:
            errors.append(
                WorkflowError(
                    kind=ItemKind.edge,
                    id=edge["id"],
                    field="data.label",
                    message=(
                        f'Transition tool name "{function_name}" is reserved for '
                        "agent skills. Use a different edge label."
                    ),
                )
            )
    return errors


def reserved_custom_tool_name_error(
    node_id: str, function_name: str, tool_name: str
) -> WorkflowError | None:
    if function_name not in SKILL_BUILTIN_FUNCTION_NAMES:
        return None
    return WorkflowError(
        kind=ItemKind.node,
        id=node_id,
        field="data.tool_uuids",
        message=(
            f'Custom tool "{tool_name}" generates LLM tool name '
            f'"{function_name}", which is reserved for agent skills. '
            "Rename the tool."
        ),
    )
