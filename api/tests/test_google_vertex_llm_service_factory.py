from types import SimpleNamespace
from unittest.mock import patch

from api.services.configuration.check_validity import UserConfigurationValidator
from api.services.configuration.registry import (
    REGISTRY,
    GoogleVertexLLMConfiguration,
    ServiceProviders,
    ServiceType,
)
from api.services.pipecat.service_factory import (
    create_llm_service,
    create_llm_service_from_provider,
)
from api.services.pipecat.vertex_llm import VertexModelFamily, vertex_model_family


class TestGoogleVertexLLMConfiguration:
    def test_defaults(self):
        config = GoogleVertexLLMConfiguration(project_id="demo-project")
        assert config.provider == ServiceProviders.GOOGLE_VERTEX
        assert config.model == "gemini-3.5-flash"
        assert config.location == "global"
        assert config.credentials is None
        assert config.api_key is None

    def test_registered_in_llm_registry(self):
        assert ServiceProviders.GOOGLE_VERTEX in REGISTRY[ServiceType.LLM]
        assert (
            REGISTRY[ServiceType.LLM][ServiceProviders.GOOGLE_VERTEX]
            is GoogleVertexLLMConfiguration
        )


class TestGoogleVertexLLMServiceFactory:
    def test_create_llm_service_from_provider_uses_vertex_service(self):
        with patch(
            "api.services.pipecat.service_factory.DograhGoogleVertexLLMService"
        ) as mock_service:
            create_llm_service_from_provider(
                provider=ServiceProviders.GOOGLE_VERTEX.value,
                model="gemini-2.5-pro",
                api_key=None,
                project_id="demo-project",
                location="us-central1",
                credentials='{"type":"service_account"}',
            )

        kwargs = mock_service.call_args.kwargs
        assert kwargs["project_id"] == "demo-project"
        assert kwargs["location"] == "us-central1"
        assert kwargs["credentials"] == '{"type":"service_account"}'
        assert kwargs["settings"].model == "gemini-2.5-pro"
        assert kwargs["settings"].temperature == 0.1

    def test_create_llm_service_extracts_vertex_credentials(self):
        user_config = SimpleNamespace(
            llm=SimpleNamespace(
                provider=ServiceProviders.GOOGLE_VERTEX.value,
                api_key=None,
                model="gemini-3.5-flash",
                project_id="demo-project",
                location="us-east4",
                credentials='{"type":"service_account"}',
            )
        )

        with patch(
            "api.services.pipecat.service_factory.DograhGoogleVertexLLMService"
        ) as mock_service:
            create_llm_service(user_config)

        kwargs = mock_service.call_args.kwargs
        assert kwargs["project_id"] == "demo-project"
        assert kwargs["location"] == "us-east4"
        assert kwargs["credentials"] == '{"type":"service_account"}'


class TestGoogleVertexModelFamilyRouting:
    def test_model_family_table(self):
        cases = {
            "gemini-3.5-flash": "gemini",
            "gemini-3.5-pro": "gemini",
            "gemma-3-27b": "gemini",
            "google/gemma": "gemini",
            "": "gemini",
            "claude-sonnet-4-6": "anthropic",
            "claude-haiku-4-5@20251001": "anthropic",
            "anthropic/claude-sonnet-5": "anthropic",
            "meta/llama-3.3-70b-instruct-maas": "openai_compat",
            "deepseek-ai/deepseek-v3.2-maas": "openai_compat",
            "qwen/qwen3-coder-480b-a35b-instruct-maas": "openai_compat",
            "openai/gpt-oss-120b-maas": "openai_compat",
            "moonshotai/kimi-k2-thinking-maas": "openai_compat",
            "my-custom-model": "openai_compat",
        }
        for model, family in cases.items():
            assert vertex_model_family(model) == VertexModelFamily(family), model

    def test_every_catalogued_model_resolves_to_the_expected_service(self):
        """Pins the routing table to the catalogue: a new id landing in the
        wrong family silently sends users to an endpoint that 404s."""
        from api.services.configuration.options.google import GOOGLE_VERTEX_MODELS

        expected = {
            VertexModelFamily.GEMINI: "gemini",
            VertexModelFamily.ANTHROPIC: "claude",
            VertexModelFamily.OPENAI_COMPAT: "maas",
        }
        for model in GOOGLE_VERTEX_MODELS:
            family = vertex_model_family(model)
            if model.startswith(("gemini", "gemma")):
                assert expected[family] == "gemini", model
            elif model.startswith("claude"):
                assert expected[family] == "claude", model
            else:
                assert expected[family] == "maas", model

    def test_claude_model_routes_to_anthropic_service(self):
        with patch(
            "api.services.pipecat.vertex_anthropic_llm.DograhVertexAnthropicLLMService"
        ) as mock_service:
            create_llm_service_from_provider(
                provider=ServiceProviders.GOOGLE_VERTEX.value,
                model="claude-sonnet-4-6",
                api_key=None,
                project_id="demo-project",
                location="global",
                credentials='{"type":"service_account"}',
            )

        kwargs = mock_service.call_args.kwargs
        assert kwargs["project_id"] == "demo-project"
        assert kwargs["location"] == "global"
        assert kwargs["credentials"] == '{"type":"service_account"}'
        assert kwargs["settings"].model == "claude-sonnet-4-6"
        assert kwargs["settings"].temperature == 0.1

    def test_claude_location_defaults_to_global(self):
        with patch(
            "api.services.pipecat.vertex_anthropic_llm.DograhVertexAnthropicLLMService"
        ) as mock_service:
            create_llm_service_from_provider(
                provider=ServiceProviders.GOOGLE_VERTEX.value,
                model="claude-haiku-4-5@20251001",
                api_key=None,
                project_id="demo-project",
                location=None,
                credentials=None,
            )

        assert mock_service.call_args.kwargs["location"] == "global"

    def test_claude_sonnet_5_omits_temperature(self):
        from anthropic import NOT_GIVEN

        with patch(
            "api.services.pipecat.vertex_anthropic_llm.DograhVertexAnthropicLLMService"
        ) as mock_service:
            create_llm_service_from_provider(
                provider=ServiceProviders.GOOGLE_VERTEX.value,
                model="claude-sonnet-5",
                api_key=None,
                project_id="demo-project",
                location="global",
                credentials=None,
            )

        assert mock_service.call_args.kwargs["settings"].temperature is NOT_GIVEN

    def test_maas_model_routes_to_maas_service(self):
        with patch(
            "api.services.pipecat.vertex_llm.DograhVertexMaaSLLMService"
        ) as mock_service:
            create_llm_service_from_provider(
                provider=ServiceProviders.GOOGLE_VERTEX.value,
                model="meta/llama-3.3-70b-instruct-maas",
                api_key=None,
                project_id="demo-project",
                location="us-central1",
                credentials='{"type":"service_account"}',
            )

        kwargs = mock_service.call_args.kwargs
        assert kwargs["project_id"] == "demo-project"
        assert kwargs["location"] == "us-central1"
        assert kwargs["credentials"] == '{"type":"service_account"}'
        assert kwargs["settings"].model == "meta/llama-3.3-70b-instruct-maas"
        assert kwargs["settings"].temperature == 0.1


class TestGoogleVertexLLMValidation:
    def test_validator_accepts_vertex_llm_without_api_key(self):
        validator = UserConfigurationValidator()
        config = GoogleVertexLLMConfiguration(
            project_id="demo-project",
            location="us-east4",
            credentials='{"type":"service_account"}',
        )

        assert validator._validate_service(config, "llm") == []

    def test_validator_requires_project_id(self):
        validator = UserConfigurationValidator()
        config = SimpleNamespace(
            provider=ServiceProviders.GOOGLE_VERTEX.value,
            project_id=None,
            location="us-east4",
            credentials='{"type":"service_account"}',
            api_key=None,
        )

        result = validator._validate_service(config, "llm")

        assert result == [
            {"model": "llm", "message": "project_id is required for Google Vertex"}
        ]
