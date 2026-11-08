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


# Examples that name one kind of business ("Bloom Dental"). Shown only to
# agents made from that same kind of template; anyone else gets these.
_NEUTRAL_PLACEHOLDERS = {
    "business_name": None,
    "business_description": None,
    "website": "https://yourbusiness.ie",
    "extra_info": None,
}


def known_fact_questions(category: str | None = None) -> dict[str, TemplateSetupField]:
    """The stored setup questions of every starter template, by key. With a
    ``category``, that kind of template's questions (and examples) come first;
    examples naming another kind of business are replaced with neutral ones."""
    from api.services.workflow.starter_templates import STARTER_TEMPLATES

    starters = sorted(
        STARTER_TEMPLATES, key=lambda s: 0 if category and s.category == category else 1
    )
    questions: dict[str, TemplateSetupField] = {}
    for starter in starters:
        own = (
            category is not None
            and category != "general"
            and starter.category == category
        )
        for field in starter.setup_fields:
            if not field.stored or field.key in questions:
                continue
            if category is not None and not own and field.key in _NEUTRAL_PLACEHOLDERS:
                field = field.model_copy(
                    update={"placeholder": _NEUTRAL_PLACEHOLDERS[field.key]}
                )
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
    facts = facts or {}
    if questions is None:
        from api.services.call_review.categories import template_for_workflow

        questions = known_fact_questions(template_for_workflow(definition, facts))
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
        if field.type == "languages":
            from api.services.workflow.agent_languages import (
                AgentLanguagesError,
                normalised_agent_languages,
            )

            try:
                value = normalised_agent_languages(value) or ""
            except AgentLanguagesError as exc:
                raise BusinessFactsError(str(exc)) from None
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


# "Pass calls to your team": the number the transfer tool dials.
TRANSFER_NUMBER_KEY = "transfer_number"


def checked_transfer_number(value: str | None, own_numbers: list[str]) -> str | None:
    """The transfer number as it is stored and dialled (E.164, or a SIP
    destination as typed); None when emptied. Raises BusinessFactsError with
    the owner-facing reason for a number that can't be called or is one of
    the agent's own numbers (*own_numbers*)."""
    from api.utils.transfer_number import check_transfer_number

    check = check_transfer_number(value or "", own_numbers=own_numbers)
    if not check.ok:
        raise BusinessFactsError(check.error or "That number can't be used.")
    return check.value or None
