import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from pipecat.services.anthropic.llm import AnthropicLLMSettings
from pipecat.services.openai.base_llm import OpenAILLMSettings

from api.services.pipecat.vertex_llm import (
    _GoogleCredentialsAuth,
    build_vertex_llm_service,
)


def _make_anthropic_service(**kwargs):
    from api.services.pipecat.vertex_anthropic_llm import (
        DograhVertexAnthropicLLMService,
    )

    with (
        patch(
            "api.services.pipecat.vertex_anthropic_llm.service_account_credentials"
        ) as mock_creds,
        patch(
            "api.services.pipecat.vertex_anthropic_llm.AsyncAnthropicVertex"
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


class TestBuildVertexLLMService:
    def test_gemini_model_uses_the_injected_builder(self):
        sentinel = object()
        service = build_vertex_llm_service(
            "gemini-3.5-flash",
            project_id="demo-project",
            location=None,
            credentials=None,
            gemini_builder=lambda: sentinel,
        )
        assert service is sentinel

    def test_missing_anthropic_package_is_an_actionable_400(self):
        """A deployment without the extra must get a config error for Claude,
        not a raw ModuleNotFoundError."""
        with patch.dict(
            "sys.modules", {"api.services.pipecat.vertex_anthropic_llm": None}
        ):
            with pytest.raises(HTTPException) as exc_info:
                build_vertex_llm_service(
                    "claude-sonnet-4-6",
                    project_id="demo-project",
                    location=None,
                    credentials=None,
                    gemini_builder=lambda: None,
                )
        assert exc_info.value.status_code == 400
        assert "anthropic" in exc_info.value.detail


class TestDograhVertexAnthropicLLMService:
    def test_constructs_vertex_client_from_credentials(self):
        service, mock_creds, mock_client_cls = _make_anthropic_service(
            location="us-east5"
        )

        mock_creds.assert_called_once_with('{"type":"service_account"}')
        kwargs = mock_client_cls.call_args.kwargs
        assert kwargs["project_id"] == "demo-project"
        assert kwargs["region"] == "us-east5"
        assert kwargs["credentials"] is mock_creds.return_value

    def test_location_defaults_to_global(self):
        _, _, mock_client_cls = _make_anthropic_service()
        assert mock_client_cls.call_args.kwargs["region"] == "global"

    def test_beta_endpoint_calls_are_redirected_to_the_non_beta_one(self):
        """pipecat hardcodes client.beta.messages.create plus a beta header
        Vertex rejects; the client proxy must strip both."""
        service, _, _ = _make_anthropic_service()
        inner = MagicMock()
        inner.messages.create = AsyncMock(return_value="response")
        service._client._client = inner
        service._client.beta.messages._client = inner

        result = asyncio.run(
            service._client.beta.messages.create(
                model="claude-sonnet-4-6", stream=True, betas=["x"]
            )
        )

        assert result == "response"
        call_kwargs = inner.messages.create.await_args.kwargs
        assert "betas" not in call_kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-6"
        inner.beta.messages.create.assert_not_called()

    def test_non_proxied_attributes_reach_the_real_client(self):
        service, _, mock_client_cls = _make_anthropic_service()
        assert service._client.close is mock_client_cls.return_value.close


class TestDograhVertexMaaSLLMService:
    def _make(self, location):
        from api.services.pipecat.vertex_llm import DograhVertexMaaSLLMService

        with patch(
            "api.services.pipecat.vertex_llm.service_account_credentials"
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
        creds = self._creds(valid=True)
        auth = _GoogleCredentialsAuth(creds)
        request = httpx.Request("POST", "https://example.com")

        flow = auth.sync_auth_flow(request)
        sent = next(flow)

        assert sent.headers["Authorization"] == "Bearer tok-123"
        creds.refresh.assert_not_called()

    def test_async_flow_refreshes_expired_credentials(self):
        creds = self._creds(valid=False)
        auth = _GoogleCredentialsAuth(creds)
        request = httpx.Request("POST", "https://example.com")

        async def run():
            flow = auth.async_auth_flow(request)
            return await anext(flow)

        sent = asyncio.run(run())

        assert sent.headers["Authorization"] == "Bearer tok-123"
        creds.refresh.assert_called_once()

    def test_concurrent_refreshes_mint_one_token(self):
        """Without the lock every concurrent request refreshes independently."""
        creds = self._creds(valid=False)

        def refresh(_request):
            creds.valid = True

        creds.refresh.side_effect = refresh
        auth = _GoogleCredentialsAuth(creds)

        async def one():
            request = httpx.Request("POST", "https://example.com")
            flow = auth.async_auth_flow(request)
            return await anext(flow)

        async def run():
            return await asyncio.gather(*(one() for _ in range(5)))

        results = asyncio.run(run())

        creds.refresh.assert_called_once()
        assert all(r.headers["Authorization"] == "Bearer tok-123" for r in results)
