"""Answer one help question: retrieve guide sections, ask Gemini, check the
answer against the guardrails.

Privacy: the question and the answer are never stored or logged. The log
line carries metadata only (who, which screen, which sections, outcome,
tokens, time); feedback stores the same metadata plus up or down.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from loguru import logger

from api.services.help_assistant import guardrails
from api.services.help_assistant.knowledge import Chunk, get_index, normalise_page
from api.services.help_assistant.links import ALLOWED_PATHS, sanitize_links

AnswerKind = Literal["answer", "not_covered", "off_topic", "unavailable"]

# Guide sections handed to the model per question.
TOP_K = 5
HELP_MAX_OUTPUT_TOKENS = 700
HELP_TEMPERATURE = 0.1


@dataclass(slots=True)
class HelpReply:
    id: str
    kind: AnswerKind
    answer: str
    links: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)  # chunk ids
    guard: str | None = None  # which output check fired, for the log only


# (organization_id, system, user, schema) -> raw JSON text
ModelCall = Callable[[int, str, str, dict], Awaitable[str]]


async def _gemini(organization_id: int, system: str, user: str, schema: dict) -> str:
    from api.services.call_review.llm import ask_reviewer

    reply = await ask_reviewer(
        organization_id=organization_id,
        system=system,
        user=user,
        schema=schema,
        temperature=HELP_TEMPERATURE,
        max_output_tokens=HELP_MAX_OUTPUT_TOKENS,
    )
    return reply.text


def build_prompt(question: str, page: str | None, chunks: list[Chunk]) -> str:
    screen = ALLOWED_PATHS.get(page or "", None)
    where = f"{page} ({screen})" if screen else (page or "unknown")
    sections = "\n\n".join(
        f"[{i}] {c.title}\n{c.text}" for i, c in enumerate(chunks, start=1)
    )
    return (
        f"The user is on the screen: {where}\n\n"
        f"<knowledge>\n{sections}\n</knowledge>\n\n"
        f"{guardrails.fence_question(question)}"
    )


def _fixed(
    kind: AnswerKind, guard: str | None = None
) -> tuple[AnswerKind, str, str | None]:
    text = {
        "off_topic": guardrails.OFF_TOPIC_TEXT,
        "not_covered": guardrails.NOT_COVERED_TEXT,
        "unavailable": guardrails.UNAVAILABLE_TEXT,
    }[kind]
    return kind, text, guard


# "…screen: 1. Open X. 2. Press Y." -> one step per line.
_INLINE_STEP = re.compile(r"(?<=[.!?:)*])\s+(?=\d{1,2}\.\s+[A-Z*\[])")


def format_steps(text: str) -> str:
    """Put numbered steps the model ran together onto their own lines."""
    if re.search(r"^\s*\d{1,2}\.\s", text, re.MULTILINE) and "\n" in text:
        return text
    return _INLINE_STEP.sub("\n", text)


def check_answer(raw: str, knowledge: str) -> tuple[AnswerKind, str, str | None]:
    """The model's JSON -> (kind, text, guard that fired)."""
    try:
        data = json.loads(raw)
        kind = data.get("kind")
        text = str(data.get("answer") or "").strip()
    except (ValueError, AttributeError):
        return _fixed("unavailable", "bad_json")
    if kind in ("off_topic", "not_covered"):
        return _fixed(kind)
    if kind != "answer" or not text:
        return _fixed("not_covered", "empty")
    if guardrails.leaks_instructions(text):
        return _fixed("off_topic", "instructions_leak")
    if guardrails.contains_secret(text):
        return _fixed("off_topic", "secret")
    if guardrails.unsupported_amounts(text, knowledge):
        return _fixed("not_covered", "unsupported_price")
    if len(text) > guardrails.MAX_ANSWER_CHARS:
        text = text[: guardrails.MAX_ANSWER_CHARS].rsplit("\n", 1)[0].rstrip()
    return "answer", text, None


async def answer_question(
    *,
    organization_id: int,
    user_id: int,
    question: str,
    page: str | None,
    agent_id: int | None,
    model_call: ModelCall | None = None,
) -> HelpReply:
    started = time.monotonic()
    reply_id = uuid.uuid4().hex
    page = normalise_page(page)
    question = question.strip()[: guardrails.MAX_QUESTION_CHARS]

    hits: list[Chunk] = []
    if guardrails.contains_secret(question):
        reply = HelpReply(
            reply_id,
            "off_topic",
            guardrails.SECRET_IN_QUESTION_TEXT,
            guard="secret_in_question",
        )
    else:
        hits = [
            chunk for chunk, _ in get_index().search(question, page=page, limit=TOP_K)
        ]
        if not hits:
            # Nothing in the guides shares a word with the question: no call.
            reply = HelpReply(
                reply_id, "not_covered", guardrails.NO_MATCH_TEXT, guard="no_match"
            )
        else:
            call = model_call or _gemini
            try:
                raw = await call(
                    organization_id,
                    guardrails.SYSTEM_PROMPT,
                    build_prompt(question, page, hits),
                    guardrails.ANSWER_SCHEMA,
                )
                kind, text, guard = check_answer(raw, "\n".join(c.text for c in hits))
            except Exception as exc:  # noqa: BLE001 - any failure is "try again"
                logger.warning(
                    f"help assistant model call failed: {type(exc).__name__}"
                )
                kind, text, guard = _fixed("unavailable", "model_error")
            links: list[str] = []
            if kind == "answer":
                text, links = sanitize_links(format_steps(text), agent_id)
            reply = HelpReply(
                reply_id,
                kind,
                text,
                links=links,
                sources=[c.id for c in hits] if kind == "answer" else [],
                guard=guard,
            )

    # Metadata only: never the question or the answer.
    logger.info(
        "help_ask "
        + json.dumps(
            {
                "id": reply.id,
                "org": organization_id,
                "user": user_id,
                "page": page,
                "kind": reply.kind,
                "guard": reply.guard,
                "sources": [c.id for c in hits],
                "question_chars": len(question),
                "ms": round((time.monotonic() - started) * 1000),
            }
        )
    )
    return reply
