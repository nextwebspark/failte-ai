"""Parse and chunk one uploaded document for the knowledge base task."""

from __future__ import annotations

import asyncio

from api.services.documents.chunk import (
    DEFAULT_OVERLAP_TOKENS,
    DEFAULT_TARGET_TOKENS,
    chunk_document,
)
from api.services.documents.parse import ParsedDocument, parse_document

PARSER_NAME = "lightmove"


def _metadata(parsed: ParsedDocument) -> dict:
    metadata = {
        "parser": PARSER_NAME,
        "format": parsed.format,
        "title": parsed.title,
        "sections": len(parsed.sections),
    }
    if parsed.page_count is not None:
        metadata["pages"] = parsed.page_count
    return metadata


def _process(
    path: str,
    filename: str,
    content_type: str | None,
    retrieval_mode: str,
    max_tokens: int,
    overlap_tokens: int,
) -> dict:
    parsed = parse_document(path, filename, content_type)
    metadata = _metadata(parsed)
    if retrieval_mode == "full_document":
        return {
            "mode": "full_document",
            "docling_metadata": metadata,
            "full_text": parsed.full_text,
        }
    chunks = chunk_document(
        parsed, max_tokens=max_tokens, overlap_tokens=overlap_tokens
    )
    metadata["chunks"] = len(chunks)
    return {"mode": "chunked", "docling_metadata": metadata, "chunks": chunks}


async def process_document(
    path: str,
    filename: str,
    content_type: str | None,
    retrieval_mode: str,
    *,
    max_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> dict:
    """Parse the file and return its full text or its chunks.

    Returns ``{"mode", "docling_metadata", "full_text"}`` in ``full_document``
    mode and ``{"mode", "docling_metadata", "chunks"}`` in ``chunked`` mode,
    each chunk carrying ``chunk_text``, ``contextualized_text``,
    ``chunk_index``, ``chunk_metadata`` and ``token_count``. Raises
    DocumentParseError, whose message is meant for the user, when the file
    has no usable text.
    """
    # Parsing a PDF or Word file is CPU-bound; keep the event loop free.
    return await asyncio.to_thread(
        _process,
        path,
        filename,
        content_type,
        retrieval_mode,
        max_tokens,
        overlap_tokens,
    )
