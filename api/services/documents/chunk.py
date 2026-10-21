"""Split parsed documents into overlapping, heading-aware chunks for search.

Chunks never cross a heading, never split a word and prefer to end at a
paragraph, line or sentence break. Sizes are estimated from words and
characters rather than with a tokenizer, so this needs no model files: about
4/3 tokens per word, or one per 4 characters for long words such as URLs.
"""

from __future__ import annotations

import math
import re
from bisect import bisect_right
from dataclasses import dataclass

from api.services.documents.parse import ParsedDocument, Section

DEFAULT_TARGET_TOKENS = 400
DEFAULT_OVERLAP_TOKENS = 50

_WORD = re.compile(r"\S+")
_SENTENCE_END = re.compile(r"[.!?:;][\"')\]]*$")
# A chunk may end early, at a better break, once it holds this share of its budget.
_MIN_FILL_BEFORE_BREAK = 0.6


@dataclass(frozen=True)
class _Word:
    start: int
    end: int
    cost: float
    page: int | None
    # How good a place the gap after this word is to end a chunk (0 = mid-sentence).
    break_score: int


def _word_cost(word: str) -> float:
    return max(4 / 3, len(word) / 4)


def estimate_tokens(text: str) -> int:
    """Rough token count of *text* (no tokenizer)."""
    return math.ceil(sum(_word_cost(word) for word in _WORD.findall(text)))


def chunk_document(
    parsed: ParsedDocument,
    *,
    max_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[dict]:
    """Chunks in the shape the processing task stores, in document order."""
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    overlap_tokens = max(0, min(overlap_tokens, max_tokens // 2))

    chunks: list[dict] = []
    for section in parsed.sections:
        for text, pages in _split_section(section, max_tokens, overlap_tokens):
            metadata: dict = {"headings": list(section.headings)}
            if pages:
                metadata["page_numbers"] = pages
            chunks.append(
                {
                    "chunk_text": text,
                    "contextualized_text": _contextualize(
                        parsed.title, section.headings, text
                    ),
                    "chunk_index": len(chunks),
                    "chunk_metadata": metadata,
                    "token_count": estimate_tokens(text),
                }
            )
    return chunks


def _contextualize(title: str, headings: tuple[str, ...], text: str) -> str:
    path = list(headings)
    if path and path[0].casefold() == title.casefold():
        path = path[1:]
    prefix = " > ".join([title, *path]) if title else " > ".join(path)
    return f"{prefix}\n\n{text}" if prefix else text


def _split_section(
    section: Section, max_tokens: int, overlap_tokens: int
) -> list[tuple[str, list[int]]]:
    text, words = _words(section)
    pieces: list[tuple[str, list[int]]] = []
    start = 0
    while start < len(words):
        end = _window_end(words, start, max_tokens)
        chunk_words = words[start:end]
        pages = sorted({w.page for w in chunk_words if w.page is not None})
        pieces.append((text[chunk_words[0].start : chunk_words[-1].end], pages))
        if end >= len(words):
            break
        start = _overlap_start(words, start, end, overlap_tokens)
    return pieces


def _words(section: Section) -> tuple[str, list[_Word]]:
    """The section's text and its words, each tagged with its PDF page."""
    parts: list[str] = []
    block_starts: list[int] = []
    offset = 0
    for block in section.blocks:
        block_starts.append(offset)
        parts.append(block.text)
        offset += len(block.text) + 2
    text = "\n\n".join(parts)

    matches = list(_WORD.finditer(text))
    words: list[_Word] = []
    for index, match in enumerate(matches):
        block = section.blocks[bisect_right(block_starts, match.start()) - 1]
        if index + 1 < len(matches):
            gap = text[match.end() : matches[index + 1].start()]
            if "\n\n" in gap:
                score = 3
            elif "\n" in gap:
                score = 2
            elif _SENTENCE_END.search(match.group()):
                score = 1
            else:
                score = 0
        else:
            score = 3
        words.append(
            _Word(
                start=match.start(),
                end=match.end(),
                cost=_word_cost(match.group()),
                page=block.page,
                break_score=score,
            )
        )
    return text, words


def _window_end(words: list[_Word], start: int, max_tokens: int) -> int:
    """Exclusive end of the chunk starting at *start*."""
    total = 0.0
    end = start
    while end < len(words) and (end == start or total + words[end].cost <= max_tokens):
        total += words[end].cost
        end += 1
    if end >= len(words):
        return end

    # Back up to the best break in the last part of the window, if there is one.
    earliest = start + max(1, math.ceil((end - start) * _MIN_FILL_BEFORE_BREAK))
    best_index, best_score = end - 1, words[end - 1].break_score
    for index in range(end - 1, earliest - 2, -1):
        if words[index].break_score > best_score:
            best_index, best_score = index, words[index].break_score
    return best_index + 1 if best_score > 0 else end


def _overlap_start(
    words: list[_Word], start: int, end: int, overlap_tokens: int
) -> int:
    """Where the next chunk starts: far enough back to repeat ~overlap_tokens."""
    total = 0.0
    next_start = end
    while (
        next_start - 1 > start and total + words[next_start - 1].cost <= overlap_tokens
    ):
        next_start -= 1
        total += words[next_start].cost
    return next_start
