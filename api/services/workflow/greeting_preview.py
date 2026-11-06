"""The words a voice preview on "What your agent knows" reads out.

Pure functions, no I/O. The text always comes from the stored agent, never
from the browser: synthesis costs money, so a caller can't make the server
read out arbitrary text, and each greeting + voice pair is generated once
(see ``google_voices.preview_audio``'s disk cache).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

# Long enough for any real greeting; a pasted essay is cut at a sentence.
MAX_PREVIEW_CHARS = 300

# Only the platform's own voices (Google Chirp 3 HD) are previewed here.
CHIRP_VOICE_ID = re.compile(r"^[a-z]{2,3}-[A-Z]{2}-Chirp3-HD-[A-Za-z]{2,32}$")

_FACT = re.compile(r"\{\{\s*initial_context\.([a-z][a-z0-9_]*)\s*\}\}", re.IGNORECASE)
_OTHER_PLACEHOLDER = re.compile(r"\{\{.*?\}\}")
_SPACES = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([,.!?])")
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")


def start_greeting(definition: Mapping[str, Any] | None) -> str | None:
    """The start step's spoken greeting, or None when it plays a recording
    or has none."""
    nodes = (definition or {}).get("nodes")
    if not isinstance(nodes, list):
        return None
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        data = node.get("data")
        if not isinstance(data, Mapping):
            continue
        if data.get("is_start") is True or node.get("type") == "startCall":
            if data.get("greeting_type") == "audio" and data.get(
                "greeting_recording_id"
            ):
                return None
            text = data.get("greeting")
            return (text.strip() or None) if isinstance(text, str) else None
    return None


def fill_greeting(text: str, facts: Mapping[str, Any] | None) -> str:
    """``{{initial_context.key}}`` from the agent's facts, as callers hear it
    (the same rules as the page's ``fillGreeting``). Any other placeholder is
    a per-call value the preview can't know, so it is left out rather than
    read out as braces."""
    facts = facts or {}

    def fact(match: re.Match[str]) -> str:
        value = facts.get(match.group(1))
        return value.strip() if isinstance(value, str) else ""

    filled = _FACT.sub(fact, text)
    filled = _OTHER_PLACEHOLDER.sub("", filled)
    filled = _SPACES.sub(" ", filled)
    filled = _SPACE_BEFORE_PUNCTUATION.sub(r"\1", filled)
    return filled.strip()


def shorten(text: str, limit: int = MAX_PREVIEW_CHARS) -> str:
    """*text*, cut at the last sentence end within *limit* (else the last
    word) when it is longer."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    ends = [m.end() for m in _SENTENCE_END.finditer(head)]
    if ends:
        return head[: ends[-1]].strip()
    return head.rsplit(" ", 1)[0].strip() or head


def greeting_preview_text(
    definition: Mapping[str, Any] | None, facts: Mapping[str, Any] | None
) -> str | None:
    """What the preview reads: the filled, shortened greeting, or None when
    there is no spoken greeting to read (the fixed sample is used then)."""
    greeting = start_greeting(definition)
    if greeting is None:
        return None
    text = shorten(fill_greeting(greeting, facts))
    return text or None


def is_preview_voice(voice_id: str) -> bool:
    return bool(CHIRP_VOICE_ID.fullmatch(voice_id))
