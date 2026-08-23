"""Anthropic Claude on Vertex AI, using the org's project and credentials.

Requires the ``anthropic`` package (pipecat's ``anthropic`` extra);
:func:`api.services.pipecat.vertex_llm.build_vertex_llm_service` imports this
module lazily so Gemini-only deployments run without it.
"""

from types import SimpleNamespace

from anthropic import AsyncAnthropicVertex

from api.services.pipecat.vertex_llm import service_account_credentials
from pipecat.services.anthropic.llm import AnthropicLLMService


class _NonBetaMessages:
    """``messages.create`` minus the ``betas`` param, on the non-beta endpoint."""

    def __init__(self, client: AsyncAnthropicVertex):
        self._client = client

    async def create(self, **params):
        params.pop("betas", None)
        return await self._client.messages.create(**params)


class _VertexNonBetaClient:
    """Anthropic client proxy whose ``beta.messages.create`` is the non-beta one.

    pipecat's ``AnthropicLLMService`` hardcodes ``client.beta.messages.create``
    plus an interleaved-thinking beta header that Vertex rejects. Redirecting
    the beta surface here means every inference path the parent has — streaming
    and ``run_inference`` alike, present or future — lands on the endpoint
    Vertex accepts, without copying any parent code.
    """

    def __init__(self, client: AsyncAnthropicVertex):
        self._client = client
        self.beta = SimpleNamespace(messages=_NonBetaMessages(client))

    def __getattr__(self, name):
        return getattr(self._client, name)


class DograhVertexAnthropicLLMService(AnthropicLLMService):
    """Anthropic Claude served through the org's Vertex AI project."""

    def __init__(
        self,
        *,
        project_id: str,
        location: str | None = None,
        credentials: str | None = None,
        settings=None,
        **kwargs,
    ):
        client = AsyncAnthropicVertex(
            project_id=project_id,
            region=location or "global",
            # The SDK refreshes the OAuth token from the credentials object on
            # every request, covering calls longer than the 1-hour token life.
            credentials=service_account_credentials(credentials),
        )
        super().__init__(
            api_key="unused",
            settings=settings,
            client=_VertexNonBetaClient(client),
            **kwargs,
        )
