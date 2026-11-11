"""The call review: building the reviewer's prompt from a call and checking
what comes back. Pure functions; ``service.py`` does the reading, the model
call and the writing.

Stored at ``workflow_runs.annotations["call_review"]``::

    {"version": 1,
     "summary": "Booked a table for 4 tonight at 7:00 pm. Asked about parking.",
     "reason": "reservations", "reason_label": "Reservations",
     "unanswered_questions": ["Do you have gluten-free pasta?"],
     "time_was_full": false,
     "model": "gemini-3.1-flash-lite", "created_at": "2026-11-06T13:41:00+00:00"}
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from api.services.call_review.categories import OTHER, ReasonSet

CALL_REVIEW_KEY = "call_review"
REVIEW_VERSION = 1

# What a review keeps after the call's content is deleted (retention purge or
# erasure): the reason and the flags, which hold nothing the caller said.
# The summary and the caller's questions go with the transcript.
KEPT_AFTER_PURGE = frozenset(
    {"version", "reason", "reason_label", "time_was_full", "model", "created_at"}
)

SILENT_SUMMARY = "Hung up without speaking."
# The model id stored on reviews written without a model.
NO_MODEL = "none"

_USER = "rtf-user-transcription"
_BOT = "rtf-bot-text"

# A long call is cut in the middle: the start says why they rang, the end
# what was agreed.
MAX_TRANSCRIPT_CHARS = 8000
MAX_SUMMARY_CHARS = 300
MAX_QUESTIONS = 3
MAX_QUESTION_CHARS = 200

# Details the agent writes down that help the reviewer; numbers are left out.
_DETAIL_KEYS = (
    "caller_name",
    "call_reason",
    "booking_outcome",
    "booking_date",
    "booking_time",
    "party_size",
    "special_requests",
)


def has_caller_speech(gathered_context: Mapping[str, Any] | None) -> bool:
    """The engine tags a call ``user_speech`` once it hears the caller."""
    tags = (gathered_context or {}).get("call_tags")
    return isinstance(tags, list) and "user_speech" in tags


def transcript_lines(logs: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    """(speaker, text) per turn, as the Calls panel shows the chat: the
    caller's final transcriptions, and the agent's text with the pieces of
    one turn joined."""
    events = (logs or {}).get("realtime_feedback_events")
    lines: list[tuple[str, str]] = []
    bot_turn: Any = None
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, Mapping):
            continue
        payload = event.get("payload")
        payload = payload if isinstance(payload, Mapping) else {}
        text = payload.get("text")
        kind = event.get("type")
        if kind == _USER:
            bot_turn = None
            if isinstance(text, str) and text.strip() and payload.get("final", True):
                lines.append(("Caller", text.strip()))
        elif kind == _BOT:
            if not isinstance(text, str) or not text.strip():
                continue
            turn = event.get("turn")
            if (
                lines
                and lines[-1][0] == "Agent"
                and bot_turn is not None
                and turn == bot_turn
            ):
                lines[-1] = ("Agent", f"{lines[-1][1]} {text.strip()}")
            else:
                lines.append(("Agent", text.strip()))
            bot_turn = turn
        else:
            bot_turn = None
    return lines


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n[... middle of the call left out ...]\n{text[-half:]}"


def _details(gathered_context: Mapping[str, Any] | None) -> list[str]:
    gathered = gathered_context or {}
    found = []
    for key in _DETAIL_KEYS:
        value = gathered.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            found.append(f"- {key.replace('_', ' ')}: {str(value).strip()[:200]}")
    return found


def system_prompt(reasons: ReasonSet) -> str:
    options = "\n".join(f'- "{r.key}": {r.label} ({r.hint})' for r in reasons.reasons)
    return (
        f"You read one phone call to {reasons.business}, answered by its "
        "automated phone assistant, and report it to the owner in plain UK "
        "English.\n\n"
        "Return JSON with:\n"
        "- summary: one or two short sentences in the past tense saying what "
        "the caller wanted and what happened. Start with a verb and leave out "
        'the subject, like: "Booked a table for 4 tonight at 7:00 pm. Asked '
        'about parking." Write times like 7:00 pm. Never mention AI, a bot, '
        "an assistant, a transcript, a system or tools.\n"
        "- reason: the one key below that best fits what the caller wanted:\n"
        f"{options}\n"
        "- unanswered_questions: each question the caller asked that the "
        "assistant could not answer (it did not know, could not say, or would "
        "pass it on), written as the caller's short question. [] if none.\n"
        "- time_was_full: true only if the caller wanted a date or time that "
        "was full or not available."
    )


def user_prompt(
    lines: Sequence[tuple[str, str]], gathered_context: Mapping[str, Any] | None
) -> str:
    call = "\n".join(f"{speaker}: {text}" for speaker, text in lines)
    details = _details(gathered_context)
    parts = []
    if details:
        parts.append("Details written down on the call:\n" + "\n".join(details))
    parts.append("The call:\n" + _clip(call, MAX_TRANSCRIPT_CHARS))
    return "\n\n".join(parts)


def response_schema(reasons: ReasonSet) -> dict[str, Any]:
    """The JSON schema the model must answer in."""
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "reason": {"type": "string", "enum": list(reasons.keys)},
            "unanswered_questions": {"type": "array", "items": {"type": "string"}},
            "time_was_full": {"type": "boolean"},
        },
        "required": ["summary", "reason", "unanswered_questions", "time_was_full"],
    }


class ReviewParseError(ValueError):
    """The model's answer can't be used."""


def _one_line(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _cut(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def parse_review(
    text: str | None,
    reasons: ReasonSet,
    *,
    model: str,
    now: datetime,
) -> dict[str, Any]:
    """The stored review from the model's JSON answer. An unknown reason
    becomes "other"; anything missing or of the wrong shape is either
    defaulted (no questions, time not full) or, for the summary, an error."""
    try:
        data = json.loads(text or "")
    except (TypeError, ValueError) as exc:
        raise ReviewParseError("not JSON") from exc
    if not isinstance(data, dict):
        raise ReviewParseError("not an object")
    summary = data.get("summary")
    if not isinstance(summary, str) or not _one_line(summary):
        raise ReviewParseError("no summary")
    reason = data.get("reason")
    reason = reason.strip().lower() if isinstance(reason, str) else OTHER
    if reason not in reasons.keys:
        reason = OTHER
    raw_questions = data.get("unanswered_questions")
    questions: list[str] = []
    for question in raw_questions if isinstance(raw_questions, list) else []:
        if isinstance(question, str) and _one_line(question):
            cleaned = _cut(_one_line(question), MAX_QUESTION_CHARS)
            if cleaned not in questions:
                questions.append(cleaned)
    return {
        "version": REVIEW_VERSION,
        "summary": _cut(_one_line(summary), MAX_SUMMARY_CHARS),
        "reason": reason,
        "reason_label": reasons.label(reason),
        "unanswered_questions": questions[:MAX_QUESTIONS],
        "time_was_full": data.get("time_was_full") is True,
        "model": model,
        "created_at": now.isoformat(),
    }


def silent_review(reasons: ReasonSet, *, now: datetime) -> dict[str, Any]:
    """The review of a call where the caller never spoke; no model needed."""
    return {
        "version": REVIEW_VERSION,
        "summary": SILENT_SUMMARY,
        "reason": OTHER,
        "reason_label": reasons.label(OTHER),
        "unanswered_questions": [],
        "time_was_full": False,
        "model": NO_MODEL,
        "created_at": now.isoformat(),
    }


def stored_review(annotations: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """The review on a run, or None when it has none (or a malformed one)."""
    review = (annotations or {}).get(CALL_REVIEW_KEY)
    if isinstance(review, Mapping) and isinstance(review.get("reason"), str):
        return review
    return None


def purged_review(review: Any) -> dict[str, Any] | None:
    """What of a review survives the deletion of the call's content."""
    if not isinstance(review, Mapping):
        return None
    kept = {key: review[key] for key in KEPT_AFTER_PURGE if key in review}
    return kept or None
