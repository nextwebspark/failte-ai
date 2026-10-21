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


# Sharing and retries --------------------------------------------------------------


async def test_services_share_credentials_and_the_http_client(monkeypatch):
    from api.services.pipecat import vertex_llm

    calls = []

    def fake_credentials(credentials_json):
        calls.append(credentials_json)
        return SimpleNamespace(valid=True, token="shared-token")

    monkeypatch.setattr(vertex_llm, "service_account_credentials", fake_credentials)
    monkeypatch.setattr(vertex_service, "_TOKENS", {})
    sent = []

    async def handler(request):
        sent.append(request.headers["Authorization"])
        return httpx.Response(200, json=_prediction([1.0] * 1536))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(vertex_service, "shared_http_client", lambda: client)

    for _ in range(3):  # three live-call lookups
        service = VertexEmbeddingService(
            db_client=None, project_id="eu-project", credentials='{"sa": 1}'
        )
        await service.embed_query("hours?")
    other = VertexEmbeddingService(
        db_client=None, project_id="eu-project", credentials='{"sa": 2}'
    )
    await other.embed_query("hours?")

    assert calls == ['{"sa": 1}', '{"sa": 2}']
    assert sent == ["Bearer shared-token"] * 4
    assert vertex_service.shared_token(None) is vertex_service.shared_token(None)


async def test_shared_http_client_is_reused_per_event_loop():
    first = vertex_service.shared_http_client()
    assert vertex_service.shared_http_client() is first
    await first.aclose()
    assert vertex_service.shared_http_client() is not first


async def test_rate_limits_honour_retry_after(monkeypatch):
    waits = []

    async def record_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(vertex_service.asyncio, "sleep", record_sleep)
    vertex = _Vertex(
        responses=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json=_prediction([1.0] * 1536)),
        ]
    )
    service = vertex.service()

    await service.embed_texts(["hello"])

    # (0.01 is the fake endpoint's own delay.)
    assert [w for w in waits if w != 0.01] == [7.0]


@pytest.mark.parametrize(
    ("method", "attempts"),
    [("embed_texts", 6), ("embed_query", 3)],
)
async def test_documents_wait_out_rate_limits_longer_than_queries(method, attempts):
    vertex = _Vertex(responses=[httpx.Response(429)] * 10)
    service = vertex.service()

    with pytest.raises(VertexEmbeddingError, match="HTTP 429"):
        argument = ["hello"] if method == "embed_texts" else "hello"
        await getattr(service, method)(argument)

    assert len(vertex.requests) == attempts


async def test_a_failure_cancels_the_other_requests():
    started = []

    async def handler(request):
        content = json.loads(request.content)["instances"][0]["content"]
        started.append(content)
        if content == "bad":
            return httpx.Response(400, json={"error": {"message": "Bad input"}})
        await asyncio.sleep(10)
        return httpx.Response(200, json=_prediction([1.0] * 1536))

    async def token():
        return "t"

    service = VertexEmbeddingService(
        db_client=None,
        project_id="eu-project",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        token_provider=token,
        max_concurrency=2,
    )

    with pytest.raises(VertexEmbeddingError, match="Bad input"):
        await asyncio.wait_for(
            service.embed_texts(["bad", "slow", "never-1", "never-2"]), timeout=5
        )

    # The queue stops once a request fails (the freed slot may already have
    # gone to the next text).
    assert "never-2" not in started


# EmbeddingSettings.from_config for the other providers ------------------------------


async def test_settings_from_azure_config():
    from api.services.configuration.registry import AzureOpenAIEmbeddingsConfiguration
    from api.services.gen_ai import AzureOpenAIEmbeddingService

    settings = EmbeddingSettings.from_config(
        AzureOpenAIEmbeddingsConfiguration(
            api_key="az-key",
            endpoint="https://example.openai.azure.com",
            model="kb-embeddings",
        )
    )

    assert (settings.provider, settings.api_key, settings.model) == (
        "azure",
        "az-key",
        "kb-embeddings",
    )
    assert settings.endpoint == "https://example.openai.azure.com"
    assert settings.api_version == "2024-02-15-preview"
    assert settings.is_configured
    service = await build_embedding_service(db_client=None, settings=settings)
    assert isinstance(service, AzureOpenAIEmbeddingService)
    assert service.get_model_id() == "kb-embeddings"


async def test_settings_from_openrouter_config():
    from api.services.configuration.registry import OpenRouterEmbeddingsConfiguration

    settings = EmbeddingSettings.from_config(
        OpenRouterEmbeddingsConfiguration(api_key="or-key")
    )

    assert settings.provider == "openrouter"
    assert settings.base_url == "https://openrouter.ai/api/v1"
    assert settings.model == "openai/text-embedding-3-small"
    service = await build_embedding_service(db_client=None, settings=settings)
    assert isinstance(service, OpenAIEmbeddingService)
    assert str(service.client.base_url).startswith("https://openrouter.ai/api/v1")


async def test_settings_from_managed_config_use_the_mps_base_url(mps_configured):
    from api.services.configuration.registry import DograhEmbeddingsConfiguration
    from api.services.gen_ai import DograhEmbeddingService

    settings = EmbeddingSettings.from_config(
        DograhEmbeddingsConfiguration(api_key="mps_sk_1")
    )

    assert settings.provider == "dograh"
    assert settings.base_url == f"{mps_configured}/api/v1/llm"
    assert settings.model == "dograh_embedding_v1"
    service = await build_embedding_service(
        db_client=None, settings=settings, correlation_id="cid-1"
    )
    assert isinstance(service, DograhEmbeddingService)
    assert service.get_model_id() == "dograh_embedding_v1"


def test_settings_from_managed_config_without_mps_refuse(monkeypatch):
    from api.errors.mps import MPSNotConfiguredError
    from api.services import mps_service_key_client as mps_client_module
    from api.services.configuration.registry import DograhEmbeddingsConfiguration

    monkeypatch.setattr(mps_client_module, "MPS_API_URL", "")
    monkeypatch.setattr(mps_client_module.mps_service_key_client, "base_url", "")

    with pytest.raises(MPSNotConfiguredError):
        EmbeddingSettings.from_config(DograhEmbeddingsConfiguration(api_key="k"))
