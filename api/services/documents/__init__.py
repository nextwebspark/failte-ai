"""Knowledge base document processing that runs on this server.

Uploaded files are parsed and chunked in-process, so their content is never
sent to another service. Only chunk text goes on to the organization's
configured embedding provider.
"""

from api.services.documents.chunk import (
    DEFAULT_OVERLAP_TOKENS,
    DEFAULT_TARGET_TOKENS,
    chunk_document,
    estimate_tokens,
)
from api.services.documents.parse import (
    SUPPORTED_EXTENSIONS,
    DocumentParseError,
    ParsedDocument,
    parse_document,
)
from api.services.documents.processor import process_document

__all__ = [
    "DEFAULT_OVERLAP_TOKENS",
    "DEFAULT_TARGET_TOKENS",
    "SUPPORTED_EXTENSIONS",
    "DocumentParseError",
    "ParsedDocument",
    "chunk_document",
    "estimate_tokens",
    "parse_document",
    "process_document",
]
