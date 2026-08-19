"""Anthropic Claude and open MaaS models served through the org's Vertex AI project.

Vertex AI exposes three model families behind one provider config
(project_id / location / service-account credentials):

- Gemini — handled by ``DograhGoogleVertexLLMService`` in ``service_factory``.
- Anthropic Claude — native Anthropic Messages API via ``AsyncAnthropicVertex``.
- Open MaaS models (Llama, DeepSeek, Qwen, gpt-oss, ...) — the OpenAI-compatible
  ``.../endpoints/openapi`` endpoint.

This module requires the ``anthropic`` package (pipecat's ``anthropic`` extra);
``service_factory`` imports it lazily so Gemini-only deployments work without it.
"""

import asyncio

import httpx
from anthropic import AsyncAnthropicVertex
from loguru import logger
from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.google.vertex.llm import GoogleVertexLLMService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.settings import assert_given

# MaaS models are served from specific regions only; requests against the
# "global" location fail, so configs using the (default) global location are
# mapped to this region instead.
_DEFAULT_MAAS_REGION = "us-central1"


class DograhVertexAnthropicLLMService(AnthropicLLMService):
    """Anthropic Claude on Vertex AI using the org's project and credentials.

    Vertex rejects the first-party ``interleaved-thinking`` beta header the
    parent injects, so both inference paths are overridden to call the
    non-beta Messages endpoint without ``betas``.
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
        google_creds = GoogleVertexLLMService._get_credentials(credentials, None)
        client = AsyncAnthropicVertex(
            project_id=project_id,
            region=location or "global",
            # The SDK refreshes the OAuth token from the credentials object on
            # every request, covering calls longer than the 1-hour token life.
            credentials=google_creds,
        )
        super().__init__(api_key="unused", settings=settings, client=client, **kwargs)

    async def _create_message_stream(self, api_call, params):
        params = {k: v for k, v in params.items() if k != "betas"}
        return await super()._create_message_stream(
            self._client.messages.create, params
        )

    async def run_inference(self, context, max_tokens=None, system_instruction=None):
        # Mirrors AnthropicLLMService.run_inference, minus the beta header and
        # beta endpoint that Vertex rejects.
        effective_instruction = system_instruction or assert_given(
            self._settings.system_instruction
        )
        adapter = self.get_llm_adapter()
        invocation_params = adapter.get_llm_invocation_params(
            context,
            enable_prompt_caching=assert_given(self._settings.enable_prompt_caching),
            system_instruction=effective_instruction,
            ensure_last_message_is_user=self._should_inject_trailing_user_message(),
        )

        params = {
            "model": self._settings.model,
            "max_tokens": max_tokens
            if max_tokens is not None
            else self._settings.max_tokens,
            "stream": False,
            "temperature": self._settings.temperature,
            "top_k": self._settings.top_k,
            "top_p": self._settings.top_p,
            "messages": invocation_params["messages"],
            "system": invocation_params["system"],
            "tools": invocation_params["tools"],
        }
        thinking = assert_given(self._settings.thinking)
        if thinking:
            params["thinking"] = thinking.model_dump(exclude_unset=True)
        params.update(self._settings.extra)
        params.pop("betas", None)

        response = await self._client.messages.create(**params)

        return next(
            (block.text for block in response.content if hasattr(block, "text")), None
        )


class _GoogleCredentialsAuth(httpx.Auth):
    """httpx auth flow that injects a fresh Vertex OAuth bearer token per request."""

    def __init__(self, creds):
        self._creds = creds

    def sync_auth_flow(self, request):
        from google.auth.transport.requests import Request as GoogleAuthRequest

        if not self._creds.valid:
            self._creds.refresh(GoogleAuthRequest())
        request.headers["Authorization"] = f"Bearer {self._creds.token}"
        yield request

    async def async_auth_flow(self, request):
        from google.auth.transport.requests import Request as GoogleAuthRequest

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
        self._google_creds = GoogleVertexLLMService._get_credentials(credentials, None)
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
                limits=httpx.Limits(
                    max_keepalive_connections=100,
                    max_connections=1000,
                    keepalive_expiry=None,
                ),
            ),
        )
