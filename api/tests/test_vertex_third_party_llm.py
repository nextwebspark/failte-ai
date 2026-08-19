import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pipecat.services.anthropic.llm import AnthropicLLMSettings
from pipecat.services.openai.base_llm import OpenAILLMSettings


def _make_anthropic_service(**kwargs):
    from api.services.pipecat.vertex_llm import DograhVertexAnthropicLLMService

    with (
        patch(
            "api.services.pipecat.vertex_llm.GoogleVertexLLMService._get_credentials"
        ) as mock_creds,
        patch(
            "api.services.pipecat.vertex_llm.AsyncAnthropicVertex"
        ) as mock_client_cls,
    ):
        mock_creds.return_value = MagicMock(name="google_creds")
        service = DograhVertexAnthropicLLMService(
            project_id=kwargs.pop("project_id", "demo-project"),
            location=kwargs.pop("location", None),
            credentials=kwargs.pop("credentials", '{"type":"service_account"}'),
            settings=kwargs.pop(
                "settings",
                AnthropicLLMSettings(model="claude-sonnet-4-6", temperature=0.1),
            ),
        )
    return service, mock_creds, mock_client_cls


class TestDograhVertexAnthropicLLMService:
    def test_constructs_vertex_client_from_credentials(self):
        service, mock_creds, mock_client_cls = _make_anthropic_service(
            location="us-east5"
        )

        mock_creds.assert_called_once_with('{"type":"service_account"}', None)
        kwargs = mock_client_cls.call_args.kwargs
        assert kwargs["project_id"] == "demo-project"
        assert kwargs["region"] == "us-east5"
        assert kwargs["credentials"] is mock_creds.return_value
        assert service._client is mock_client_cls.return_value

    def test_location_defaults_to_global(self):
        _, _, mock_client_cls = _make_anthropic_service()
        assert mock_client_cls.call_args.kwargs["region"] == "global"

    def test_message_stream_strips_betas_and_uses_non_beta_endpoint(self):
        service, _, _ = _make_anthropic_service()
        service._client = MagicMock()
        service._client.messages.create = AsyncMock(return_value="stream")

        result = asyncio.run(
            service._create_message_stream(
                service._client.beta.messages.create,
                {"model": "claude-sonnet-4-6", "stream": True, "betas": ["x"]},
            )
        )

        assert result == "stream"
        service._client.messages.create.assert_awaited_once()
        call_kwargs = service._client.messages.create.await_args.kwargs
        assert "betas" not in call_kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-6"
        service._client.beta.messages.create.assert_not_called()

    def test_run_inference_uses_non_beta_endpoint(self):
        from pipecat.processors.aggregators.llm_context import LLMContext

        service, _, _ = _make_anthropic_service()
        text_block = MagicMock()
        text_block.text = "hello"
        service._client = MagicMock()
        service._client.messages.create = AsyncMock(
            return_value=MagicMock(content=[text_block])
        )

        context = LLMContext(messages=[{"role": "user", "content": "hi"}])
        result = asyncio.run(
            service.run_inference(context, system_instruction="You are a test bot.")
        )

        assert result == "hello"
        call_kwargs = service._client.messages.create.await_args.kwargs
        assert "betas" not in call_kwargs
        assert call_kwargs["stream"] is False
        service._client.beta.messages.create.assert_not_called()


class TestDograhVertexMaaSLLMService:
    def _make(self, location):
        from api.services.pipecat.vertex_llm import DograhVertexMaaSLLMService

        with patch(
            "api.services.pipecat.vertex_llm.GoogleVertexLLMService._get_credentials"
        ) as mock_creds:
            mock_creds.return_value = MagicMock(name="google_creds")
            service = DograhVertexMaaSLLMService(
                project_id="demo-project",
                location=location,
                credentials='{"type":"service_account"}',
                settings=OpenAILLMSettings(
                    model="meta/llama-3.3-70b-instruct-maas", temperature=0.1
                ),
            )
        return service

    def test_regional_location_builds_base_url(self):
        service = self._make("us-east5")
        assert str(service._client.base_url) == (
            "https://us-east5-aiplatform.googleapis.com/v1/projects/"
            "demo-project/locations/us-east5/endpoints/openapi/"
        )

    @pytest.mark.parametrize("location", [None, "", "global"])
    def test_global_or_unset_location_maps_to_default_region(self, location):
        service = self._make(location)
        assert "us-central1-aiplatform.googleapis.com" in str(service._client.base_url)


class TestGoogleCredentialsAuth:
    def _creds(self, valid):
        creds = MagicMock()
        creds.valid = valid
        creds.token = "tok-123"
        return creds

    def test_sync_flow_sets_bearer_and_skips_refresh_when_valid(self):
        import httpx

        from api.services.pipecat.vertex_llm import _GoogleCredentialsAuth

        creds = self._creds(valid=True)
        auth = _GoogleCredentialsAuth(creds)
        request = httpx.Request("POST", "https://example.com")

        flow = auth.sync_auth_flow(request)
        sent = next(flow)

        assert sent.headers["Authorization"] == "Bearer tok-123"
        creds.refresh.assert_not_called()

    def test_async_flow_refreshes_expired_credentials(self):
        import httpx

        from api.services.pipecat.vertex_llm import _GoogleCredentialsAuth

        creds = self._creds(valid=False)
        auth = _GoogleCredentialsAuth(creds)
        request = httpx.Request("POST", "https://example.com")

        async def run():
            flow = auth.async_auth_flow(request)
            return await anext(flow)

        sent = asyncio.run(run())

        assert sent.headers["Authorization"] == "Bearer tok-123"
        creds.refresh.assert_called_once()
