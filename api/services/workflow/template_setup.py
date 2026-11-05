"""Fill a workflow template with the answers to its setup questions."""

import re
from collections.abc import Mapping
from typing import Any

from pydantic import TypeAdapter, ValidationError

from api.schemas.call_summary_email import (
    CALL_SUMMARY_EMAIL_KEY,
    MAX_CALL_SUMMARY_RECIPIENTS,
    CallSummaryEmailConfiguration,
)
from api.schemas.workflow_template import (
    TemplateSetupField,
    TemplateSetupPrefill,
    TemplateSetupSetting,
)

_FIELDS = TypeAdapter(list[TemplateSetupField])
_ADDRESS_SEPARATORS = re.compile(r"[,;\s]+")


class TemplateSetupError(ValueError):
    """The answers don't fit the template's setup questions."""


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
) -> dict[str, Any]:
    """Return a copy of *definition* with each field's ``{{key}}`` replaced.

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
        value = (values.get(field.key) or "").strip()
        if not value and field.required:
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

    filled: dict[str, Any] = fill(definition)
    return filled


def setup_configurations(
    fields: list[TemplateSetupField],
    values: Mapping[str, str],
    *,
    user_email: str | None,
) -> dict[str, Any]:
    """The workflow configuration set by the answers to *fields* that have a
    ``setting``.

    An answer that was not sent at all falls back to the field's prefill; one
    sent blank leaves the setting off. Raises TemplateSetupError for an answer
    the user gave that the setting rejects; a prefill it rejects (a creator
    address such as admin@localhost) leaves the setting off instead.
    """
    configurations: dict[str, Any] = {}
    for field in fields:
        if field.setting is None:
            continue
        typed = field.key in values
        answer = (
            values[field.key].strip() if typed else _prefill(field.prefill, user_email)
        )
        match field.setting:
            case TemplateSetupSetting.CALL_SUMMARY_RECIPIENTS:
                configurations[CALL_SUMMARY_EMAIL_KEY] = _call_summary_email(
                    field, answer, typed=typed
                )
    return configurations


def _prefill(prefill: TemplateSetupPrefill | None, user_email: str | None) -> str:
    match prefill:
        case TemplateSetupPrefill.USER_EMAIL:
            return user_email or ""
        case None:
            return ""


def _call_summary_email(
    field: TemplateSetupField, answer: str, *, typed: bool
) -> dict[str, Any]:
    recipients = [a for a in _ADDRESS_SEPARATORS.split(answer) if a]
    try:
        setting = CallSummaryEmailConfiguration(
            enabled=bool(recipients), recipients=recipients
        )
    except ValidationError:
        if not typed:
            return CallSummaryEmailConfiguration().model_dump(mode="json")
        raise TemplateSetupError(
            f"{field.label}: enter up to {MAX_CALL_SUMMARY_RECIPIENTS} email "
            "addresses, separated by commas."
        ) from None
    return setting.model_dump(mode="json")


INTEGRATION_TOOL_PREFIX = "integration:"


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
