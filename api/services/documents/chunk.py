"""Split parsed documents into overlapping, heading-aware chunks for search.

Chunks never cross a heading and prefer to end at a paragraph, line or
sentence break. Words are kept whole unless a single "word" is too long to be
one (a URL, a base64 blob, or Chinese/Japanese text written without spaces);
those are cut into character windows. Sizes are estimated from words and
characters rather than with a tokenizer, so this needs no model files: about
4/3 tokens per word, one per 4 characters for long words, and one per CJK
character.
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
_SENTENCE_END = re.compile(r"[.!?:;。！？；][\"')\]」』）]*$")
# Hiragana, katakana, CJK ideographs, Hangul and full-width forms: about one
# token per character.
_CJK = re.compile(
    r"[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]"
)
_SENTENCE_CHARS = frozenset(".!?;。！？；")
# A "word" estimated above this is cut into character windows of this size.
_MAX_PIECE_TOKENS = 32
# The "title > heading > heading" prefix embedded with every chunk.
_MAX_PREFIX_CHARS = 300
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


def _char_cost(char: str) -> float:
    return 1.0 if _CJK.match(char) else 0.25


def _word_cost(word: str) -> float:
    cjk = len(_CJK.findall(word))
    return max(4 / 3, cjk + (len(word) - cjk) / 4)


def estimate_tokens(text: str) -> int:
    """Rough token count of *text* (no tokenizer)."""
    return math.ceil(sum(_word_cost(word) for word in _WORD.findall(text)))


def _pieces(word: str, start: int) -> list[tuple[int, int, float]]:
    """(start, end, cost) of *word*, cut into windows if it's too long.

    A window ends after the last sentence end in its second half when there
    is one, so text written without spaces still splits between sentences.
    """
    cost = _word_cost(word)
    if cost <= _MAX_PIECE_TOKENS:
        return [(start, start + len(word), cost)]
    costs = [_char_cost(char) for char in word]
    pieces: list[tuple[int, int, float]] = []
    piece_start = 0
    while piece_start < len(word):
        end, total, last_sentence_end = piece_start, 0.0, None
        while end < len(word) and (
            end == piece_start or total + costs[end] <= _MAX_PIECE_TOKENS
        ):
            total += costs[end]
            end += 1
            if word[end - 1] in _SENTENCE_CHARS:
                last_sentence_end = end
        if (
            end < len(word)
            and last_sentence_end is not None
            and last_sentence_end - piece_start > (end - piece_start) // 2
        ):
            end = last_sentence_end
        pieces.append(
            (start + piece_start, start + end, max(sum(costs[piece_start:end]), 1.0))
        )
        piece_start = end
    return pieces


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
        prefix = _context_prefix(parsed.title, section.headings)
        # The prefix is embedded with every chunk, so it counts against the
        # budget (never below half of it: the prefix itself is capped).
        budget = max(max_tokens // 2, max_tokens - estimate_tokens(prefix))
        overlap = min(overlap_tokens, budget // 2)
        for text, pages in _split_section(section, budget, overlap):
            metadata: dict = {"headings": list(section.headings)}
            if pages:
                metadata["page_numbers"] = pages
            chunks.append(
                {
                    "chunk_text": text,
                    "contextualized_text": f"{prefix}\n\n{text}" if prefix else text,
                    "chunk_index": len(chunks),
                    "chunk_metadata": metadata,
                    "token_count": estimate_tokens(text),
                }
            )
    return chunks


def _context_prefix(title: str, headings: tuple[str, ...]) -> str:
    path = list(headings)
    if path and path[0].casefold() == title.casefold():
        path = path[1:]
    prefix = " > ".join(part for part in [title, *path] if part)
    if len(prefix) <= _MAX_PREFIX_CHARS:
        return prefix
    # Keep the start (title) and the end (the nearest heading), drop the middle.
    keep = (_MAX_PREFIX_CHARS - 5) // 2
    return f"{prefix[:keep].rstrip()} … {prefix[-keep:].lstrip()}"


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
        pieces = _pieces(match.group(), match.start())
        for number, (start, end, cost) in enumerate(pieces):
            if number + 1 < len(pieces):
                # Inside an over-long word: a sentence end is the best break.
                piece_score = 1 if _SENTENCE_END.search(text[start:end]) else 0
            else:
                piece_score = score
            words.append(
                _Word(
                    start=start,
                    end=end,
                    cost=cost,
                    page=block.page,
                    break_score=piece_score,
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
