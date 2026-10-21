"""Embedding services for document processing and retrieval."""

from .azure_openai_service import (
    AzureEmbeddingAPIKeyNotConfiguredError,
    AzureOpenAIEmbeddingService,
)
from .base import BaseEmbeddingService
from .dograh_service import DograhEmbeddingService
from .factory import (
    EmbeddingSettings,
    build_embedding_service,
    resolve_embedding_correlation_id,
)
from .openai_service import EmbeddingAPIKeyNotConfiguredError, OpenAIEmbeddingService
from .vertex_service import VertexEmbeddingError, VertexEmbeddingService

__all__ = [
    "AzureEmbeddingAPIKeyNotConfiguredError",
    "AzureOpenAIEmbeddingService",
    "BaseEmbeddingService",
    "DograhEmbeddingService",
    "EmbeddingAPIKeyNotConfiguredError",
    "EmbeddingSettings",
    "OpenAIEmbeddingService",
    "VertexEmbeddingError",
    "VertexEmbeddingService",
    "build_embedding_service",
    "resolve_embedding_correlation_id",
]
