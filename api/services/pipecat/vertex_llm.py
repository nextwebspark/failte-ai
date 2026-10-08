"""Model-family routing and services for the Google Vertex LLM provider.

Vertex AI exposes three model families behind one provider config
(project_id / location / service-account credentials):

- Gemini — pipecat's native ``GoogleVertexLLMService`` (built by the caller,
  so this module stays importable without the ``anthropic`` package).
- Anthropic Claude — native Anthropic Messages API via ``AsyncAnthropicVertex``
  (:mod:`api.services.pipecat.vertex_anthropic_llm`, imported lazily because it
  needs pipecat's ``anthropic`` extra).
- Open MaaS models (Llama, DeepSeek, Qwen, gpt-oss, ...) — the
  OpenAI-compatible ``.../endpoints/openapi`` endpoint.
"""

import asyncio
import importlib
from collections.abc import Callable
from enum import Enum

from fastapi import HTTPException
from loguru import logger
from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from pipecat.services.google.vertex.llm import GoogleVertexLLMService
from pipecat.services.openai.base_llm import OpenAILLMSettings
from pipecat.services.openai.llm import OpenAILLMService

# MaaS models are served from specific regions only; requests against the
# "global" location fail, so configs using the (default) global location are
# mapped to this region instead.
_DEFAULT_MAAS_REGION = "us-central1"

# Claude models that reject non-default sampling params (temperature) with a
# 400. Prefix-matched so dated snapshots (claude-sonnet-5@...) are covered.
_TEMPERATURE_UNSUPPORTED_PREFIXES = (
    "claude-sonnet-5",
    "claude-opus-5",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-fable",
)

_VERTEX_TEMPERATURE = 0.1


class VertexModelFamily(str, Enum):
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"
    OPENAI_COMPAT = "openai_compat"


def vertex_model_family(model: str) -> VertexModelFamily:
    """Pick the Vertex AI API surface for a model id.

    Anything that is neither Gemini nor Claude routes to the OpenAI-compatible
    endpoint on purpose: the model field accepts custom values, and that
    endpoint is the surface that serves every open MaaS publisher — a typo'd
    id fails there with Vertex's own error rather than here.
    """
    m = (model or "").lower()
    if not m or m.startswith(("gemini", "gemma", "google/")):
        return VertexModelFamily.GEMINI
    if m.startswith(("claude", "anthropic/")):
        return VertexModelFamily.ANTHROPIC
    return VertexModelFamily.OPENAI_COMPAT


def build_vertex_llm_service(
    model: str,
    *,
    project_id: str,
    location: str | None,
    credentials: str | None,
    gemini_builder: Callable[[], object],
):
    """Build the right LLM service for a Vertex model id.

    ``gemini_builder`` constructs the Gemini service so the Gemini path never
    imports the ``anthropic`` package — deployments without pipecat's
    ``anthropic`` extra keep working for Gemini models.
    """
    family = vertex_model_family(model)
    if family is VertexModelFamily.GEMINI:
        return gemini_builder()

    if family is VertexModelFamily.ANTHROPIC:
        try:
            from anthropic import NOT_GIVEN as ANTHROPIC_NOT_GIVEN

            from api.services.pipecat.vertex_anthropic_llm import (
                DograhVertexAnthropicLLMService,
            )
            from pipecat.services.anthropic.llm import AnthropicLLMSettings
        except ImportError as e:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Claude models on Vertex require the 'anthropic' package; "
                    "install pipecat's 'anthropic' extra to enable them."
                ),
            ) from e
        temperature = (
            ANTHROPIC_NOT_GIVEN
            if model.lower().startswith(_TEMPERATURE_UNSUPPORTED_PREFIXES)
            else _VERTEX_TEMPERATURE
        )
        return DograhVertexAnthropicLLMService(
            credentials=credentials,
            project_id=project_id,
            location=location or "global",
            settings=AnthropicLLMSettings(model=model, temperature=temperature),
        )

    return DograhVertexMaaSLLMService(
        credentials=credentials,
        project_id=project_id,
        location=location,
        settings=OpenAILLMSettings(model=model, temperature=_VERTEX_TEMPERATURE),
    )


def service_account_credentials(credentials_json: str | None):
    """Google credentials from the org's pasted service-account JSON, or ADC.

    Single wrapper around pipecat's private ``_get_credentials`` so an upstream
    rename is a one-line fix here. Blocking: performs a token refresh.
    """
    return GoogleVertexLLMService._get_credentials(credentials_json, None)


# openai 2.x builds its HTTP client on ``httpx``, 3.x on ``httpx2``. The client
# rejects auth/limits objects from the other library, so take them from
# whichever one DefaultAsyncHttpxClient actually subclasses.
_http = importlib.import_module(
    DefaultAsyncHttpxClient.__mro__[1].__module__.split(".", 1)[0]
)


class _GoogleCredentialsAuth(_http.Auth):
    """httpx auth flow that injects a fresh Vertex OAuth bearer token per request."""

    def __init__(self, creds):
        self._creds = creds
        # Concurrent requests must not each mint a token while others read it.
        self._refresh_lock = asyncio.Lock()

    def sync_auth_flow(self, request):
        from google.auth.transport.requests import Request as GoogleAuthRequest

        if not self._creds.valid:
            self._creds.refresh(GoogleAuthRequest())
        request.headers["Authorization"] = f"Bearer {self._creds.token}"
        yield request

    async def async_auth_flow(self, request):
        from google.auth.transport.requests import Request as GoogleAuthRequest

        if not self._creds.valid:
            async with self._refresh_lock:
                if not self._creds.valid:
                    await asyncio.to_thread(self._creds.refresh, GoogleAuthRequest())
        request.headers["Authorization"] = f"Bearer {self._creds.token}"
        yield request


class DograhVertexMaaSLLMService(OpenAILLMService):
    """Open MaaS models (Llama, DeepSeek, Qwen, gpt-oss, ...) on Vertex AI.

    Talks to Vertex's OpenAI-compatible endpoint, authenticating with an OAuth
    bearer token derived from the org's service-account credentials.
    """

    def __init__(
        self,
        *,
        project_id: str,
        location: str | None = None,
        credentials: str | None = None,
        settings=None,
        **kwargs,
    ):
        self._google_creds = service_account_credentials(credentials)
        region = location or ""
        if not region or region == "global":
            logger.warning(
                f"Vertex MaaS models are regional; mapping location "
                f"'{region or 'unset'}' to {_DEFAULT_MAAS_REGION}"
            )
            region = _DEFAULT_MAAS_REGION
        base_url = (
            f"https://{region}-aiplatform.googleapis.com/v1/projects/"
            f"{project_id}/locations/{region}/endpoints/openapi"
        )
        super().__init__(
            api_key="unused", base_url=base_url, settings=settings, **kwargs
        )

    def create_client(self, api_key=None, base_url=None, **kwargs):
        return AsyncOpenAI(
            # The auth flow overwrites the Authorization header on every
            # request; the OpenAI client just requires a non-empty api_key.
            api_key="unused",
            base_url=base_url,
            http_client=DefaultAsyncHttpxClient(
                auth=_GoogleCredentialsAuth(self._google_creds),
                limits=_http.Limits(
                    max_keepalive_connections=100,
                    max_connections=1000,
                    keepalive_expiry=None,
                ),
            ),
        )
