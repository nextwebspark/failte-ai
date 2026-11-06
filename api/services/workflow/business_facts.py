"""Business facts: what an agent knows about the business (opening hours,
address, FAQ…), editable by the owner after the agent is created.

Starter templates keep these answers on the agent (its template context
variables) and the prompts read them at call time as
``{{initial_context.<key>}}``; see ``template_setup.fill_template``. This
module lists which facts an agent has and checks an owner's edits.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from api.schemas.workflow_template import TemplateSetupField

_FACT_RE = re.compile(r"\{\{\s*initial_context\.([a-z][a-z0-9_]*)")
# Filled by the platform on each call, never by the owner.
_CALL_KEYS = frozenset(
    {
        "caller_number",
        "called_number",
        "direction",
        "provider",
        "telephony_configuration_id",
        "external_pbx_call",
        "phone_number",
        "campaign_id",
    }
)
DEFAULT_MAX_LENGTH = 1500


@dataclass(frozen=True)
class FactField:
    key: str
    label: str
    type: str
    help: str | None
    placeholder: str | None
    required: bool
    max_length: int
    value: str


class BusinessFactsError(ValueError):
    pass


def known_fact_questions() -> dict[str, TemplateSetupField]:
    """The stored setup questions of every starter template, by key."""
    from api.services.workflow.starter_templates import STARTER_TEMPLATES

    questions: dict[str, TemplateSetupField] = {}
    for starter in STARTER_TEMPLATES:
        for field in starter.setup_fields:
            if field.stored and field.key not in questions:
                questions[field.key] = field
    return questions


def fact_fields(
    definition: dict[str, Any] | None,
    facts: dict[str, Any] | None,
    questions: dict[str, TemplateSetupField] | None = None,
) -> list[FactField]:
    """The facts an agent's prompts read, with their current values: every
    ``{{initial_context.<key>}}`` the definition uses that is a known business
    question or already has a stored value. Call fields are excluded."""
    questions = known_fact_questions() if questions is None else questions
    facts = facts or {}
    referenced = list(dict.fromkeys(_FACT_RE.findall(json.dumps(definition or {}))))
    keys = [
        key
        for key in referenced
        if key not in _CALL_KEYS and (key in questions or key in facts)
    ]
    order = list(questions)
    keys.sort(key=lambda k: (order.index(k) if k in order else len(order), k))
    fields: list[FactField] = []
    for key in keys:
        question = questions.get(key)
        value = facts.get(key)
        fields.append(
            FactField(
                key=key,
                label=question.label
                if question
                else key.replace("_", " ").capitalize(),
                type=(question.type if question else "textarea"),
                help=question.help if question else None,
                placeholder=question.placeholder if question else None,
                required=question.required if question else False,
                max_length=question.max_length if question else DEFAULT_MAX_LENGTH,
                value=value if isinstance(value, str) else "",
            )
        )
    return fields


def checked_updates(
    fields: list[FactField], updates: dict[str, Any]
) -> dict[str, str | None]:
    """The owner's edits, cleaned: only this agent's facts, plain text within
    each field's limit, required ones not emptied. An empty value removes an
    optional fact (the prompt's fallback applies)."""
    by_key = {f.key: f for f in fields}
    unknown = sorted(set(updates) - set(by_key))
    if unknown:
        raise BusinessFactsError(f"This agent has no fact: {', '.join(unknown)}")
    cleaned: dict[str, str | None] = {}
    for key, raw in updates.items():
        field = by_key[key]
        if raw is not None and not isinstance(raw, str):
            raise BusinessFactsError(f"{field.label} must be text.")
        value = (raw or "").strip()
        if not value and field.required:
            raise BusinessFactsError(f"{field.label} can't be empty.")
        if len(value) > field.max_length:
            raise BusinessFactsError(
                f"{field.label} is too long (at most {field.max_length} characters)."
            )
        # Plain text only: an answer must not open a placeholder of its own.
        value = re.sub(r"\}\}+", "}", re.sub(r"\{\{+", "{", value))
        cleaned[key] = value or None
    return cleaned
