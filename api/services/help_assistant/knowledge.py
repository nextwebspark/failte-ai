"""The help assistant's knowledge: hand-written guides in ``knowledge/*.md``,
split into one chunk per ``##`` section and searched with BM25.

Each file starts with ``# Topic`` and ``<!-- pages: /a, /b -->`` (the in-app
screens it is about). Each section ends with ``<!-- source: ... -->`` naming the
code it was written from; comments are dropped before anything reaches the model.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_PAGES = re.compile(r"<!--\s*pages:\s*(.*?)-->", re.DOTALL)
_TOKEN = re.compile(r"[a-z0-9€]+(?:[.'][a-z0-9]+)*")
_AGENT_ID = re.compile(r"^/workflow/\d+")

# Words that carry no meaning for matching a question to a section.
_STOP = frozenset(
    """a an and are as at be by can do does for from get got how i if in into is it
    its me my of on or our so that the their them then there this to up us was we
    what when where which who why will with you your yours i'm i've don't""".split()
)


@dataclass(frozen=True, slots=True)
class Chunk:
    id: str  # "<file stem>#<n>", stable while the file's sections keep their order
    topic: str
    heading: str
    text: str
    pages: tuple[str, ...]

    @property
    def title(self) -> str:
        return f"{self.topic}: {self.heading}"


def tokenize(text: str) -> list[str]:
    words = _TOKEN.findall(text.lower())
    out: list[str] = []
    for word in words:
        if word in _STOP:
            continue
        # A light stem so "forwarding", "forwards" and "forward" meet.
        for suffix in ("ing", "es", "s", "ed"):
            if len(word) > len(suffix) + 3 and word.endswith(suffix):
                word = word[: -len(suffix)]
                break
        out.append(word)
    return out


def parse_file(stem: str, raw: str) -> list[Chunk]:
    pages_match = _PAGES.search(raw)
    pages = (
        tuple(p.strip() for p in pages_match.group(1).split(",") if p.strip())
        if pages_match
        else ()
    )
    body = _COMMENT.sub("", raw)
    topic_match = re.search(r"^# (.+)$", body, re.MULTILINE)
    topic = topic_match.group(1).strip() if topic_match else stem
    chunks: list[Chunk] = []
    for n, part in enumerate(re.split(r"^## ", body, flags=re.MULTILINE)[1:]):
        heading, _, text = part.partition("\n")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if text:
            chunks.append(Chunk(f"{stem}#{n}", topic, heading.strip(), text, pages))
    return chunks


@lru_cache(maxsize=1)
def load_chunks() -> tuple[Chunk, ...]:
    chunks: list[Chunk] = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        chunks.extend(parse_file(path.stem, path.read_text(encoding="utf-8")))
    return tuple(chunks)


def normalise_page(page: str | None) -> str | None:
    """``/workflow/12/facts?x#y`` -> ``/workflow/{agent}/facts``; junk -> None."""
    if not page:
        return None
    page = page.split("?")[0].split("#")[0].strip()
    if not re.fullmatch(r"/[A-Za-z0-9/_\-]{0,120}", page):
        return None
    page = _AGENT_ID.sub("/workflow/{agent}", page).rstrip("/") or "/"
    return page


def _page_matches(chunk_page: str, page: str) -> bool:
    return page == chunk_page or page.startswith(f"{chunk_page}/")


class Index:
    """Okapi BM25 over the chunks (title words count twice)."""

    K1 = 1.4
    B = 0.75

    def __init__(self, chunks: tuple[Chunk, ...]) -> None:
        self.chunks = chunks
        self.docs = [
            Counter(tokenize(f"{c.topic} {c.heading} {c.heading} {c.text}"))
            for c in chunks
        ]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 1.0
        df: Counter[str] = Counter()
        for doc in self.docs:
            df.update(doc.keys())
        n = len(chunks)
        self.idf = {
            term: math.log(1 + (n - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def score(self, i: int, terms: list[str]) -> float:
        doc, length = self.docs[i], self.lengths[i]
        total = 0.0
        for term in terms:
            tf = doc.get(term)
            if not tf:
                continue
            norm = tf + self.K1 * (1 - self.B + self.B * length / self.avg)
            total += self.idf.get(term, 0.0) * tf * (self.K1 + 1) / norm
        return total

    def search(
        self, query: str, *, page: str | None = None, limit: int = 5
    ) -> list[tuple[Chunk, float]]:
        terms = tokenize(query)
        page = normalise_page(page)
        scored: list[tuple[Chunk, float]] = []
        for i, chunk in enumerate(self.chunks):
            score = self.score(i, terms)
            if score <= 0:
                continue
            # The screen someone is on is a strong hint for vague questions.
            if page and any(_page_matches(p, page) for p in chunk.pages):
                score *= 1.25
            scored.append((chunk, score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:limit]


@lru_cache(maxsize=1)
def get_index() -> Index:
    return Index(load_chunks())
