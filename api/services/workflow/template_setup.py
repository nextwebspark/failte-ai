"""Fill a workflow template with the answers to its setup questions."""

import re
from collections.abc import Mapping
from typing import Any

from pydantic import TypeAdapter, ValidationError

from api.schemas.workflow_template import TemplateSetupField

_FIELDS = TypeAdapter(list[TemplateSetupField])


class TemplateSetupError(ValueError):
    """The answers don't fit the template's setup questions."""


def _join(items: list[str]) -> str:
    """ "a", "a and b", "a, b and c"."""
    if len(items) <= 2:
        return " and ".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def toggles_answer(field: TemplateSetupField, raw: str | None) -> str:
    """The instruction a ``toggles`` answer stands for.

    ``raw`` is the chosen values, comma-separated; ``None`` (not answered,
    e.g. an older client) means the defaults. Order follows the options.
    """
    if raw is None:
        chosen = {o.value for o in field.options if o.default}
    else:
        chosen = {part.strip() for part in raw.split(",") if part.strip()}
        unknown = sorted(chosen - {o.value for o in field.options})
        if unknown:
            raise TemplateSetupError(
                f"{field.label}: unknown choice {', '.join(unknown)}."
            )
    prompts = [o.prompt for o in field.options if o.value in chosen]
    return field.sentence.replace("{items}", _join(prompts)) if prompts else ""


def parse_setup_fields(raw: Any) -> list[TemplateSetupField]:
    """Read a template's stored ``setup_fields``; raise on a malformed list."""
    try:
        return _FIELDS.validate_python(raw or [])
    except ValidationError as exc:
        raise TemplateSetupError(f"Template setup fields are invalid: {exc}") from exc


def fill_template_values(
    definition: dict[str, Any],
    fields: list[TemplateSetupField],
    values: dict[str, str],
    rendered: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return a copy of *definition* with each field's ``{{key}}`` replaced.

    *values* are the user's answers, trimmed. *rendered* are answers the
    server wrote for some fields; they take precedence and are not trimmed
    (e.g. a line ending in a newline). Both are checked against the field
    and made plain text alike.

    Raises TemplateSetupError for an unknown key, a missing required answer or
    an answer over the field's length limit. An empty optional answer uses the
    placeholder's fallback text, or nothing when it has none.
    """
    if not fields:
        return definition
    by_key = {field.key: field for field in fields}
    unknown = sorted(set(values) - set(by_key))
    if unknown:
        raise TemplateSetupError(f"Unknown setup fields: {', '.join(unknown)}")

    answers: dict[str, str] = {}
    for field in fields:
        if field.type == "toggles":
            # Our own wording, not the user's text: no placeholder check.
            answers[field.key] = toggles_answer(field, values.get(field.key))
            continue
        if rendered and field.key in rendered:
            value = rendered[field.key]
        else:
            value = (values.get(field.key) or "").strip()
        if not value.strip() and field.required:
            raise TemplateSetupError(f"{field.label} is required.")
        if len(value) > field.max_length:
            raise TemplateSetupError(
                f"{field.label} is too long (at most {field.max_length} characters)."
            )
        # An answer is plain text: it must not open a placeholder of its own.
        answers[field.key] = re.sub(r"\}\}+", "}", re.sub(r"\{\{+", "{", value))

    keys = "|".join(re.escape(key) for key in answers)
    pattern = re.compile(
        r"\{\{\s*(" + keys + r")\s*(?:\|\s*(?:fallback\s*:)?\s*([^}]*?))?\s*\}\}"
    )

    def replace(match: re.Match[str]) -> str:
        return answers[match.group(1)] or (match.group(2) or "")

    def fill(node: Any) -> Any:
        if isinstance(node, str):
            return pattern.sub(replace, node)
        if isinstance(node, dict):
            return {key: fill(value) for key, value in node.items()}
        if isinstance(node, list):
            return [fill(item) for item in node]
        return node

    filled: dict[str, Any] = {key: fill(value) for key, value in definition.items()}
    return filled


def fill_template(
    definition: dict[str, Any],
    fields: list[TemplateSetupField],
    values: dict[str, str],
    rendered: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Like ``fill_template_values``, but ``stored`` fields are not written
    into the prompts: each of their placeholders becomes
    ``{{initial_context.<key>}}`` (fallback kept), and the answers are
    returned as the agent's facts, to save as its template context variables.
    Answers are checked the same way for every field. *rendered* (server
    written answers, e.g. the appointment hours line) is never stored."""
    fill_template_values(definition, fields, values, rendered)  # validates all
    stored = [
        f
        for f in fields
        if f.stored and f.type != "toggles" and f.key not in (rendered or {})
    ]
    facts = {
        f.key: (values.get(f.key) or "").strip()
        for f in stored
        if (values.get(f.key) or "").strip()
    }
    if stored:
        keys = "|".join(re.escape(f.key) for f in stored)
        pattern = re.compile(r"\{\{\s*(" + keys + r")(\s*(?:\|[^}]*)?)\}\}")

        def relabel(node: Any) -> Any:
            if isinstance(node, str):
                return pattern.sub(
                    lambda m: "{{initial_context." + m.group(1) + m.group(2) + "}}",
                    node,
                )
            if isinstance(node, dict):
                return {key: relabel(value) for key, value in node.items()}
            if isinstance(node, list):
                return [relabel(item) for item in node]
            return node

        definition = relabel(definition)
    stored_keys = {f.key for f in stored}
    baked = [f for f in fields if f.key not in stored_keys]
    remaining = {k: v for k, v in values.items() if k in {f.key for f in baked}}
    return fill_template_values(definition, baked, remaining, rendered), facts


INTEGRATION_TOOL_PREFIX = "integration:"
# A tool the platform creates for each agent made from the template (not an
# integration the user connects): today the "put through to a person" tool.
BUILTIN_TRANSFER_TOOL = "builtin:transfer-call"
# Where the transfer tool sends the call: the agent's transfer_number fact,
# which the owner edits on the Business facts screen.
TRANSFER_DESTINATION = "{{initial_context.transfer_number}}"


def uses_tool_placeholder(definition: dict[str, Any], placeholder: str) -> bool:
    return any(
        placeholder in ((node.get("data") or {}).get("tool_uuids") or [])
        for node in definition.get("nodes", [])
    )


def attach_tool_placeholder(
    definition: dict[str, Any], placeholder: str, tool_uuid: str | None
) -> dict[str, Any]:
    """Swap *placeholder* in every node's tools for *tool_uuid*, or drop it."""
    nodes = []
    for node in definition.get("nodes", []):
        data = node.get("data") or {}
        uuids = data.get("tool_uuids")
        if uuids and placeholder in uuids:
            resolved: list[Any] = []
            for uuid in uuids:
                value = tool_uuid if uuid == placeholder else uuid
                if value and value not in resolved:
                    resolved.append(value)
            node = {**node, "data": {**data, "tool_uuids": resolved}}
        nodes.append(node)
    return {**definition, "nodes": nodes}


# The tools-service provider id of Google Calendar.
GOOGLE_CALENDAR = "google-calendar"


def attach_integration_tools(
    definition: dict[str, Any], tools: dict[str, str]
) -> dict[str, Any]:
    """Swap each node's ``integration:<provider>`` tool placeholder for the
    organization's tool for that provider, or drop it when there is none.

    A template marks the steps that may use, say, Google Calendar with
    ``"tool_uuids": ["integration:google-calendar"]``; *tools* maps a provider
    to the tool uuid the user connected while setting the agent up.
    """
    nodes = []
    for node in definition.get("nodes", []):
        data = node.get("data") or {}
        uuids = data.get("tool_uuids")
        if uuids:
            resolved = []
            for uuid in uuids:
                if isinstance(uuid, str) and uuid.startswith(INTEGRATION_TOOL_PREFIX):
                    tool = tools.get(uuid.removeprefix(INTEGRATION_TOOL_PREFIX))
                    if tool and tool not in resolved:
                        resolved.append(tool)
                elif uuid not in resolved:
                    resolved.append(uuid)
            node = {**node, "data": {**data, "tool_uuids": resolved}}
        nodes.append(node)
    return {**definition, "nodes": nodes}
