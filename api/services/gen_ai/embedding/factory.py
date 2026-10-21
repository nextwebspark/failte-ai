"""Factory for embedding services, including the Dograh-managed (MPS) path.

Centralizes the provider branching (Vertex AI / Azure BYOK / Dograh-managed /
OpenAI-compatible BYOK) that was previously duplicated across document ingestion, the search route,
and the RAG tool, and resolves the MPS correlation id the same way the voice
path does.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from loguru import logger

from api.db.db_client import DBClient

from .azure_openai_service import AzureOpenAIEmbeddingService
from .base import BaseEmbeddingService
from .dograh_service import DograhEmbeddingService
from .openai_service import OpenAIEmbeddingService
from .vertex_service import VertexEmbeddingService

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_AZURE_API_VERSION = "2024-02-15-preview"


async def resolve_embedding_correlation_id(
    *,
    service_key: Optional[str],
) -> Optional[str]:
    """Mint an MPS correlation id for a managed embedding call made outside a run.

    Matches the voice path's ``_authorize_oss_managed_v2_correlation``: the
    correlation is minted via the bearer service-key endpoint, so it works for
    hosted orgs and OSS keys alike. Returns ``None`` when minting fails; MPS
    accepts un-correlated embedding calls.
    """
    if not service_key:
        return None

    # Imported lazily to avoid import-time cycles between the gen_ai and service
    # layers (matches the inline-import convention used elsewhere in the app).
    from api.services.mps_service_key_client import mps_service_key_client

    if not mps_service_key_client.is_configured:
        return None

    try:
        minted = await mps_service_key_client.create_correlation_id(
            service_key=service_key
        )
        return minted.get("correlation_id")
    except Exception as e:
        logger.warning(
            "Could not resolve MPS correlation id for managed embeddings; "
            "sending without it: {}",
            e,
        )
        return None


@dataclass(frozen=True)
class EmbeddingSettings:
    """An organization's embeddings provider, as the services need it.

    Built from the configured embeddings service with ``from_config`` and
    passed whole from configuration resolution to the service factory.
    """

    provider: Optional[str] = None
    api_key: Optional[str] = field(default=None, repr=False)
    model: Optional[str] = None
    base_url: Optional[str] = None
    endpoint: Optional[str] = None
    api_version: Optional[str] = None
    # Google Vertex AI: project, location and service-account JSON (None = ADC).
    project_id: Optional[str] = None
    location: Optional[str] = None
    credentials: Optional[str] = field(default=None, repr=False)

    @property
    def is_configured(self) -> bool:
        """Whether the provider has what it needs to authenticate."""
        from api.services.configuration.registry import ServiceProviders

        if self.provider == ServiceProviders.GOOGLE_VERTEX.value:
            # Vertex authenticates with a service account or ADC, not a key.
            return bool(self.project_id)
        return bool(self.api_key)

    @classmethod
    def from_config(cls, config: Any) -> Optional["EmbeddingSettings"]:
        """Settings for a configured embeddings service, or None without one.

        Raises MPSNotConfiguredError for the LightMove.ai-managed provider
        when no MPS is configured (its base URL lives there).
        """
        if config is None:
            return None
        from api.services.configuration.ai_model_configuration import (
            apply_managed_embeddings_base_url,
        )

        provider = getattr(config, "provider", None)
        provider = getattr(provider, "value", provider)
        return cls(
            provider=provider,
            api_key=getattr(config, "api_key", None),
            model=getattr(config, "model", None),
            base_url=apply_managed_embeddings_base_url(
                provider=provider, base_url=getattr(config, "base_url", None)
            ),
            endpoint=getattr(config, "endpoint", None),
            api_version=getattr(config, "api_version", None),
            project_id=getattr(config, "project_id", None),
            location=getattr(config, "location", None),
            credentials=getattr(config, "credentials", None),
        )


async def build_embedding_service(
    *,
    db_client: DBClient,
    settings: Optional[EmbeddingSettings],
    correlation_id: Optional[str] = None,
    resolve_correlation: bool = False,
) -> BaseEmbeddingService:
    """Construct the right embedding service for an organization's settings.

    Args:
        settings: The embeddings provider settings; None builds an unconfigured
            OpenAI service that fails with a clear "configure a key" error.
        correlation_id: A correlation id already available in context (e.g. the
            running workflow's MPS correlation id). Used for the Dograh provider.
        resolve_correlation: When True and no ``correlation_id`` is supplied, resolve
            one for the Dograh provider via ``resolve_embedding_correlation_id``
            (for calls made outside a workflow run: ingestion, manual search).
    """
    from api.services.configuration.registry import ServiceProviders

    settings = settings or EmbeddingSettings()
    provider = settings.provider

    if provider == ServiceProviders.GOOGLE_VERTEX.value:
        return VertexEmbeddingService(
            db_client=db_client,
            project_id=settings.project_id,
            location=settings.location,
            credentials=settings.credentials,
            model_id=settings.model,
        )

    model_id = settings.model or DEFAULT_EMBEDDING_MODEL

    if provider == ServiceProviders.AZURE.value and settings.endpoint:
        return AzureOpenAIEmbeddingService(
            db_client=db_client,
            api_key=settings.api_key,
            endpoint=settings.endpoint,
            model_id=model_id,
            api_version=settings.api_version or DEFAULT_AZURE_API_VERSION,
        )

    if provider == ServiceProviders.DOGRAH.value:
        cid = correlation_id
        if cid is None and resolve_correlation:
            cid = await resolve_embedding_correlation_id(service_key=settings.api_key)
        return DograhEmbeddingService(
            db_client=db_client,
            api_key=settings.api_key,
            model_id=model_id,
            base_url=settings.base_url,
            correlation_id=cid,
        )

    return OpenAIEmbeddingService(
        db_client=db_client,
        api_key=settings.api_key,
        model_id=model_id,
        base_url=settings.base_url,
    )
