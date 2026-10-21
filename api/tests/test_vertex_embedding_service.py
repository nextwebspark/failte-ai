"""Knowledge base embeddings from Vertex AI in the EU (#126)."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from api.services.configuration.registry import (
    REGISTRY,
    GoogleVertexEmbeddingsConfiguration,
    OpenAIEmbeddingsConfiguration,
    ServiceProviders,
    ServiceType,
)
from api.services.gen_ai import EmbeddingSettings, build_embedding_service
from api.services.gen_ai.embedding import vertex_service
from api.services.gen_ai.embedding.openai_service import OpenAIEmbeddingService
from api.services.gen_ai.embedding.vertex_service import (
    VertexEmbeddingError,
    VertexEmbeddingService,
)

PREDICT_URL = (
    "https://europe-west1-aiplatform.googleapis.com/v1/projects/eu-project"
    "/locations/europe-west1/publishers/google/models/gemini-embedding-001:predict"
)


def _prediction(values):
    return {"predictions": [{"embeddings": {"values": values}}]}


class _Vertex:
    """A fake Vertex predict endpoint that records what it was sent."""

    def __init__(self, responses=None):
        self.requests: list[httpx.Request] = []
        self.responses = list(responses or [])
        self.in_flight = 0
        self.max_in_flight = 0

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.01)
            if self.responses:
                return self.responses.pop(0)
            content = json.loads(request.content)["instances"][0]["content"]
            # A distinct, unnormalised vector per text: [len, 0, 0, ...].
            return httpx.Response(200, json=_prediction([len(content)] + [0] * 1535))
        finally:
            self.in_flight -= 1

    def service(self, **kwargs) -> VertexEmbeddingService:
        async def token():
            return "token-1"

        return VertexEmbeddingService(
            db_client=None,
            project_id="eu-project",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(self.handler)),
            token_provider=token,
            **kwargs,
        )


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(vertex_service, "RETRY_BASE_DELAY_SECONDS", 0)


async def test_documents_are_embedded_one_request_each_in_the_eu():
    vertex = _Vertex()

    embeddings = await vertex.service().embed_texts(["hello", "hi"])

    assert [str(r.url) for r in vertex.requests] == [PREDICT_URL, PREDICT_URL]
    bodies = [json.loads(r.content) for r in vertex.requests]
    assert sorted(b["instances"][0]["content"] for b in bodies) == ["hello", "hi"]
    for request, body in zip(vertex.requests, bodies):
        assert request.method == "POST"
        assert request.headers["Authorization"] == "Bearer token-1"
        assert body["instances"][0]["task_type"] == "RETRIEVAL_DOCUMENT"
        assert body["parameters"] == {"outputDimensionality": 1536}
    # In input order, 1536-dimensional and normalised.
    assert [len(e) for e in embeddings] == [1536, 1536]
    assert embeddings[0][0] == pytest.approx(1.0)
    assert embeddings[1][0] == pytest.approx(1.0)


async def test_queries_use_the_query_task_type():
    vertex = _Vertex()

    embedding = await vertex.service().embed_query("opening hours?")

    (request,) = vertex.requests
    body = json.loads(request.content)
    assert body["instances"] == [
        {"content": "opening hours?", "task_type": "RETRIEVAL_QUERY"}
    ]
    assert len(embedding) == 1536


async def test_concurrency_is_bounded():
    vertex = _Vertex()

    embeddings = await vertex.service(max_concurrency=3).embed_texts(
        [f"text {i}" for i in range(12)]
    )

    assert len(embeddings) == 12
    assert len(vertex.requests) == 12
    assert vertex.max_in_flight == 3


async def test_rate_limits_are_retried():
    vertex = _Vertex(
        responses=[
            httpx.Response(429, json={"error": {"message": "Quota exceeded"}}),
            httpx.Response(200, json=_prediction([1.0] * 1536)),
        ]
    )

    (embedding,) = await vertex.service().embed_texts(["hello"])

    assert len(vertex.requests) == 2
    assert len(embedding) == 1536


async def test_errors_carry_googles_message():
    vertex = _Vertex(
        responses=[
            httpx.Response(
                403, json={"error": {"message": "Permission denied on project"}}
            )
        ]
    )

    with pytest.raises(VertexEmbeddingError) as error:
        await vertex.service().embed_texts(["hello"])

    assert str(error.value) == (
        "Vertex AI embeddings request failed (HTTP 403): Permission denied on project"
    )


async def test_wrong_dimension_is_rejected():
    vertex = _Vertex(responses=[httpx.Response(200, json=_prediction([0.1] * 768))])

    with pytest.raises(VertexEmbeddingError, match="768-dimensional"):
        await vertex.service().embed_texts(["hello"])


def test_service_reports_model_and_dimension():
    service = _Vertex().service()

    assert service.get_model_id() == "gemini-embedding-001"
    assert service.get_embedding_dimension() == 1536


def test_global_location_uses_the_global_host():
    assert vertex_service.vertex_predict_url("p", "global", "m") == (
        "https://aiplatform.googleapis.com/v1/projects/p/locations/global"
        "/publishers/google/models/m:predict"
    )


async def test_credentials_come_from_the_shared_vertex_helper(monkeypatch):
    from api.services.pipecat import vertex_llm

    calls = []

    def fake_credentials(credentials_json):
        calls.append(credentials_json)
        return SimpleNamespace(valid=True, token="sa-token")

    monkeypatch.setattr(vertex_llm, "service_account_credentials", fake_credentials)
    token = vertex_service._BearerToken('{"type": "service_account"}')

    assert await token.get() == "sa-token"
    assert await token.get() == "sa-token"
    assert calls == ['{"type": "service_account"}']


async def test_search_filters_on_the_vertex_model():
    calls = {}

    class FakeDB:
        async def search_similar_chunks(self, **kwargs):
            calls.update(kwargs)
            return []

    vertex = _Vertex()
    service = vertex.service()
    service.db = FakeDB()

    await service.search_similar_chunks("hours", organization_id=7, limit=3)

    assert calls["embedding_model"] == "gemini-embedding-001"
    assert calls["organization_id"] == 7
    assert len(calls["query_embedding"]) == 1536


# Configuration and factory ------------------------------------------------------------


def test_vertex_is_a_registered_embeddings_provider():
    schema = REGISTRY[ServiceType.EMBEDDINGS][ServiceProviders.GOOGLE_VERTEX]
    assert schema is GoogleVertexEmbeddingsConfiguration
    assert schema.model_json_schema()["title"] == "Google Vertex AI (EU)"
    config = GoogleVertexEmbeddingsConfiguration(project_id="eu-project")
    assert config.location == "europe-west1"
    assert config.model == "gemini-embedding-001"
    assert config.api_key is None


async def test_factory_builds_vertex_from_settings():
    config = GoogleVertexEmbeddingsConfiguration(
        project_id="eu-project", credentials='{"type": "service_account"}'
    )
    settings = EmbeddingSettings.from_config(config)

    assert settings.is_configured  # no API key needed
    assert "service_account" not in repr(settings)
    service = await build_embedding_service(db_client=None, settings=settings)

    assert isinstance(service, VertexEmbeddingService)
    assert service.project_id == "eu-project"
    assert service.location == "europe-west1"


async def test_customer_openai_keys_keep_working():
    settings = EmbeddingSettings.from_config(
        OpenAIEmbeddingsConfiguration(api_key="sk-test")
    )

    service = await build_embedding_service(db_client=None, settings=settings)

    assert settings.is_configured
    assert isinstance(service, OpenAIEmbeddingService)
    assert service.get_model_id() == "text-embedding-3-small"


def test_settings_without_credentials_are_not_configured():
    assert EmbeddingSettings.from_config(None) is None
    assert not EmbeddingSettings(provider="openai").is_configured
    assert not EmbeddingSettings(provider="google_vertex").is_configured
