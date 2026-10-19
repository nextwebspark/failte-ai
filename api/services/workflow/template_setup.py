"""Fill a workflow template with the answers to its setup questions."""

import re
from typing import Any

from pydantic import TypeAdapter, ValidationError

from api.schemas.workflow_template import TemplateSetupField

_FIELDS = TypeAdapter(list[TemplateSetupField])


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

    return fill(definition)
