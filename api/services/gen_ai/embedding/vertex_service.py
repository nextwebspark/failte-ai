"""Embeddings from Google Vertex AI, processed in the EU by default.

Calls the regional Vertex AI ``predict`` endpoint directly, so requests stay
in the configured location (``europe-west1`` unless set otherwise). The model
returns one embedding per request, so batches are sent concurrently with a
bounded number of requests in flight.

Credentials and the HTTP client are shared per process (keyed by the
service-account JSON, or ADC), so a live call's knowledge base lookup doesn't
mint a new OAuth token or open a new TLS connection every time.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import random
import weakref
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from api.db.db_client import DBClient

from .base import BaseEmbeddingService

DEFAULT_VERTEX_EMBEDDING_MODEL = "gemini-embedding-001"
DEFAULT_VERTEX_EMBEDDING_LOCATION = "europe-west1"
# knowledge_base_chunks.embedding is Vector(1536); the model is asked for
# exactly that many dimensions.
VERTEX_EMBEDDING_DIMENSION = 1536
MAX_CONCURRENT_REQUESTS = 8
_RETRY_STATUSES = {429, 500, 502, 503, 504}
# Ingestion can wait out a rate limit; a live call's query can't wait long.
DOCUMENT_MAX_ATTEMPTS = 6
QUERY_MAX_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 1.0
_MAX_RETRY_DELAY_SECONDS = 30.0
_REQUEST_TIMEOUT_SECONDS = 30.0

TASK_TYPE_DOCUMENT = "RETRIEVAL_DOCUMENT"
TASK_TYPE_QUERY = "RETRIEVAL_QUERY"


class VertexEmbeddingError(RuntimeError):
    """Vertex AI did not return an embedding."""


def vertex_predict_url(project_id: str, location: str, model: str) -> str:
    host = (
        "aiplatform.googleapis.com"
        if location == "global"
        else f"{location}-aiplatform.googleapis.com"
    )
    return (
        f"https://{host}/v1/projects/{project_id}/locations/{location}"
        f"/publishers/google/models/{model}:predict"
    )


class _BearerToken:
    """OAuth token for the org's service account (or ADC), refreshed as needed."""

    def __init__(self, credentials_json: Optional[str]):
        self._credentials_json = credentials_json
        self._credentials = None
        self._lock = asyncio.Lock()

    async def get(self) -> str:
        async with self._lock:
            if self._credentials is None:
                # Same credential handling as the Vertex LLM services: pasted
                # service-account JSON, else Application Default Credentials.
                from api.services.pipecat.vertex_llm import (
                    service_account_credentials,
                )

                # Blocking: loads credentials and performs a token refresh.
                self._credentials = await asyncio.to_thread(
                    service_account_credentials, self._credentials_json
                )
            elif not self._credentials.valid:
                from google.auth.transport.requests import Request

                await asyncio.to_thread(self._credentials.refresh, Request())
            return self._credentials.token


_TOKENS: dict[str, _BearerToken] = {}
_CLIENTS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = (
    weakref.WeakKeyDictionary()
)


def shared_token(credentials_json: Optional[str]) -> _BearerToken:
    """One token source per service account (or ADC) for the whole process."""
    key = hashlib.sha256((credentials_json or "").encode()).hexdigest()
    token = _TOKENS.get(key)
    if token is None:
        token = _TOKENS[key] = _BearerToken(credentials_json)
    return token


def shared_http_client() -> httpx.AsyncClient:
    """A pooled client for the running event loop (clients are loop-bound)."""
    loop = asyncio.get_running_loop()
    client = _CLIENTS.get(loop)
    if client is None or client.is_closed:
        client = _CLIENTS[loop] = httpx.AsyncClient(
            timeout=httpx.Timeout(_REQUEST_TIMEOUT_SECONDS)
        )
    return client


def _retry_delay(attempt: int, response: Optional[httpx.Response] = None) -> float:
    """Exponential backoff with jitter, or the server's Retry-After."""
    if response is not None:
        retry_after = response.headers.get("Retry-After", "")
        if retry_after.isdigit():
            return min(float(retry_after), _MAX_RETRY_DELAY_SECONDS)
    delay = min(RETRY_BASE_DELAY_SECONDS * 2 ** (attempt - 1), _MAX_RETRY_DELAY_SECONDS)
    return delay * random.uniform(0.5, 1.0)


class VertexEmbeddingService(BaseEmbeddingService):
    """Embedding service for Vertex AI text embedding models."""

    def __init__(
        self,
        db_client: DBClient,
        *,
        project_id: str,
        location: Optional[str] = None,
        credentials: Optional[str] = None,
        model_id: Optional[str] = None,
        max_concurrency: int = MAX_CONCURRENT_REQUESTS,
        http_client: Optional[httpx.AsyncClient] = None,
        token_provider=None,
    ):
        if not project_id:
            raise ValueError("project_id is required for Vertex AI embeddings")
        self.db = db_client
        self.project_id = project_id
        self.location = location or DEFAULT_VERTEX_EMBEDDING_LOCATION
        self.model_id = model_id or DEFAULT_VERTEX_EMBEDDING_MODEL
        self._max_concurrency = max(1, max_concurrency)
        self._http_client = http_client
        self._token = token_provider or shared_token(credentials).get
        self._url = vertex_predict_url(self.project_id, self.location, self.model_id)
        logger.info(
            f"Vertex AI embedding service initialized: model={self.model_id}, "
            f"location={self.location}"
        )

    def get_model_id(self) -> str:
        return self.model_id

    def get_embedding_dimension(self) -> int:
        return VERTEX_EMBEDDING_DIMENSION

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return await self._embed_many(texts, TASK_TYPE_DOCUMENT, DOCUMENT_MAX_ATTEMPTS)

    async def embed_query(self, query: str) -> List[float]:
        return (await self._embed_many([query], TASK_TYPE_QUERY, QUERY_MAX_ATTEMPTS))[0]

    async def search_similar_chunks(
        self,
        query: str,
        organization_id: int,
        limit: int = 5,
        document_uuids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        query_embedding = await self.embed_query(query)
        return await self.db.search_similar_chunks(
            query_embedding=query_embedding,
            organization_id=organization_id,
            limit=limit,
            document_uuids=document_uuids,
            embedding_model=self.model_id,
        )

    async def _embed_many(
        self, texts: List[str], task_type: str, max_attempts: int
    ) -> List[List[float]]:
        if not texts:
            return []
        client = self._http_client or shared_http_client()
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def one(text: str) -> List[float]:
            async with semaphore:
                return await self._embed_one(client, text, task_type, max_attempts)

        try:
            # A failure cancels the requests still queued or in flight.
            async with asyncio.TaskGroup() as group:
                tasks = [group.create_task(one(text)) for text in texts]
        except BaseExceptionGroup as failures:  # noqa: F821 (Python 3.11+)
            raise failures.exceptions[0] from None
        return [task.result() for task in tasks]

    async def _embed_one(
        self,
        client: httpx.AsyncClient,
        text: str,
        task_type: str,
        max_attempts: int,
    ) -> List[float]:
        body = {
            "instances": [{"content": text, "task_type": task_type}],
            "parameters": {"outputDimensionality": VERTEX_EMBEDDING_DIMENSION},
        }
        for attempt in range(1, max_attempts + 1):
            token = await self._token()
            try:
                response = await client.post(
                    self._url,
                    json=body,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.RequestError as exc:
                if attempt == max_attempts:
                    raise VertexEmbeddingError(
                        "Could not reach Vertex AI for embeddings."
                    ) from exc
                await asyncio.sleep(_retry_delay(attempt))
                continue
            if response.status_code in _RETRY_STATUSES and attempt < max_attempts:
                await asyncio.sleep(_retry_delay(attempt, response))
                continue
            if response.status_code != 200:
                raise VertexEmbeddingError(
                    f"Vertex AI embeddings request failed (HTTP "
                    f"{response.status_code}){_error_detail(response)}"
                )
            return self._values(response.json())
        raise VertexEmbeddingError("Vertex AI embeddings request failed.")

    def _values(self, payload: dict) -> List[float]:
        try:
            values = payload["predictions"][0]["embeddings"]["values"]
        except (KeyError, IndexError, TypeError) as exc:
            raise VertexEmbeddingError(
                "Vertex AI returned an unexpected embeddings response."
            ) from exc
        if len(values) != VERTEX_EMBEDDING_DIMENSION:
            raise VertexEmbeddingError(
                f"Vertex AI returned {len(values)}-dimensional embeddings; "
                f"{VERTEX_EMBEDDING_DIMENSION} are required."
            )
        # Reduced-dimension embeddings aren't normalised; normalise so scores
        # are comparable across providers and indexes.
        norm = math.sqrt(sum(v * v for v in values))
        return [v / norm for v in values] if norm else list(values)


def _error_detail(response: httpx.Response) -> str:
    """Google's error message, trimmed, for the document's processing error."""
    try:
        message = response.json()["error"]["message"]
    except Exception:
        return ""
    return f": {str(message)[:300]}" if message else ""
