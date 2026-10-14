"""Tests for the local Agent Builder used when platform models are enabled."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.genai import errors as genai_errors

from api.routes import workflow as workflow_routes
from api.routes.workflow import router
from api.services.auth.depends import get_user
from api.services.configuration.platform.settings import (
    PlatformModelsNotConfiguredError,
    PlatformVertexSettings,
)
from api.services.rate_limit import get_rate_limiter
from api.services.workflow import agent_builder
from api.services.workflow.agent_builder import (
    EARLY_EXIT_PROMPT,
    MAX_STAGES,
    AgentBuilderError,
    AgentBuilderRequest,
    AgentSpec,
    CapturedFieldSpec,
    GeminiAgentSpecGenerator,
    StageSpec,
    assemble_workflow_definition,
    build_agent_workflow,
    default_agent_spec_generator,
    validate_workflow_definition,
)
from api.services.workflow.dto import ReactFlowDTO
from api.services.workflow.workflow_graph import WorkflowGraph, transition_tool_name


def _spec(stage_count: int = 2, **overrides: Any) -> AgentSpec:
    values: dict[str, Any] = {
        "name": "Dental Appointment Booker",
        "persona": "You are Mia, a friendly receptionist at a dental clinic.",
        "greeting": "Hello, thanks for calling the clinic. This is Mia.",
        "opening": StageSpec(
            name="Understand request",
            prompt="Ask how you can help today.",
            done_when="The caller has said they want to book an appointment.",
        ),
        "stages": [
            StageSpec(
                name=f"Step {index}",
                prompt=f"Handle step {index}.",
                done_when=f"Step {index} is finished.",
            )
            for index in range(1, stage_count + 1)
        ],
        "closing_prompt": "Confirm the booking, thank the caller and say goodbye.",
        "end_call_when": "The caller asks to end the call or it is a wrong number.",
        "captured_fields": [
            CapturedFieldSpec(name="Preferred Date", description="Requested date."),
            CapturedFieldSpec(name="preferred_date", description="Duplicate."),
            CapturedFieldSpec(name="patient_name", description="Caller's name."),
        ],
    }
    values.update(overrides)
    return AgentSpec(**values)


def _request(
    call_type: str = "INBOUND", activity: str = "Book appointments for patients"
) -> AgentBuilderRequest:
    return AgentBuilderRequest(
        call_type=call_type,
        use_case="dental clinic",
        activity_description=activity,
        organization_id=11,
    )


def _nodes(definition: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["id"]: node for node in definition["nodes"]}


class FakeGenerator:
    def __init__(self, *results: AgentSpec | Exception) -> None:
        self._results = list(results)
        self.calls: list[AgentBuilderRequest] = []

    async def generate(self, request: AgentBuilderRequest) -> AgentSpec:
        self.calls.append(request)
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _client_error(code: int) -> genai_errors.ClientError:
    return genai_errors.ClientError(code, {"error": {"message": "nope"}})


# --- assembler ----------------------------------------------------------------


def test_assembled_definition_passes_app_validation() -> None:
    definition = assemble_workflow_definition(_spec(), "INBOUND")

    validate_workflow_definition(definition)
    graph = WorkflowGraph(ReactFlowDTO.model_validate(definition))
    assert graph.start_node_id == "start"
    assert graph.global_node_id == "global"
    assert graph.get_required_template_variables() == set()


def test_assembled_definition_shape() -> None:
    definition = assemble_workflow_definition(_spec(stage_count=2), "INBOUND")
    nodes = _nodes(definition)
    types = [node["type"] for node in definition["nodes"]]

    assert types == [
        "startCall",
        "agentNode",
        "agentNode",
        "endCall",
        "endCall",
        "globalNode",
    ]
    start = nodes["start"]["data"]
    assert start["greeting"] == "Hello, thanks for calling the clinic. This is Mia."
    assert start["greeting_type"] == "text"
    assert start["is_start"] is True
    assert nodes["end"]["data"]["prompt"].startswith("Confirm the booking")
    assert nodes["end_early"]["data"]["prompt"] == EARLY_EXIT_PROMPT
    assert "## Voice rules" in nodes["global"]["data"]["prompt"]

    edges = {
        (edge["source"], edge["target"]): edge["data"]["label"]
        for edge in definition["edges"]
    }
    assert edges == {
        ("start", "stage_1"): "Go to Step 1",
        ("start", "end_early"): "End Call",
        ("stage_1", "stage_2"): "Go to Step 2",
        ("stage_1", "end_early"): "End Call",
        ("stage_2", "end"): "Finish Call",
        ("stage_2", "end_early"): "End Call",
    }
    assert len({edge["id"] for edge in definition["edges"]}) == len(edges)
    for edge in definition["edges"]:
        assert edge["data"]["condition"]
    # Only the last stage reaches the success close, with its own condition.
    finish = next(e for e in definition["edges"] if e["target"] == "end")
    assert finish["data"]["condition"] == "Step 2 is finished."
    # Every node except the global one is reachable from the start node.
    reachable, frontier = {"start"}, ["start"]
    while frontier:
        source = frontier.pop()
        for edge in definition["edges"]:
            if edge["source"] == source and edge["target"] not in reachable:
                reachable.add(edge["target"])
                frontier.append(edge["target"])
    assert reachable == set(nodes) - {"global"}


def test_extraction_runs_on_every_prompted_node() -> None:
    definition = assemble_workflow_definition(_spec(), "INBOUND")

    for node in definition["nodes"]:
        if node["type"] == "globalNode":
            continue
        data = node["data"]
        assert data["extraction_enabled"] is True, node["id"]
        # snake_cased and de-duplicated
        assert [v["name"] for v in data["extraction_variables"]] == [
            "preferred_date",
            "patient_name",
        ]


@pytest.mark.parametrize(
    ("call_type", "expected", "interrupt"),
    [
        ("INBOUND", "INBOUND call", False),
        ("OUTBOUND", "OUTBOUND call", True),
        ("outbound", "OUTBOUND call", True),
    ],
)
def test_call_type_sets_direction_and_start_interruption(
    call_type: str, expected: str, interrupt: bool
) -> None:
    nodes = _nodes(assemble_workflow_definition(_spec(), call_type))
    assert expected in nodes["global"]["data"]["prompt"]
    assert nodes["start"]["data"]["allow_interrupt"] is interrupt


def test_stages_are_capped_and_no_extraction_without_fields() -> None:
    definition = assemble_workflow_definition(
        _spec(stage_count=9, captured_fields=[]), "INBOUND"
    )
    validate_workflow_definition(definition)
    agent_nodes = [n for n in definition["nodes"] if n["type"] == "agentNode"]
    assert len(agent_nodes) == MAX_STAGES
    assert all(n["data"]["extraction_enabled"] is False for n in agent_nodes)


def test_long_stage_names_keep_tool_names_within_64_chars() -> None:
    long_name = "Verify the caller identity and collect every single detail " * 3
    spec = _spec(stages=[StageSpec(name=long_name, prompt="Do it.", done_when="Done.")])
    definition = assemble_workflow_definition(spec, "INBOUND")
    validate_workflow_definition(definition)
    for edge in definition["edges"]:
        assert len(transition_tool_name(edge["data"]["label"])) <= 64


def test_spec_without_stages_is_rejected() -> None:
    with pytest.raises(AgentBuilderError):
        assemble_workflow_definition(_spec(stage_count=0), "INBOUND")


def test_blank_greeting_is_rejected() -> None:
    with pytest.raises(AgentBuilderError):
        assemble_workflow_definition(_spec(greeting="   "), "INBOUND")


def test_template_variables_are_rejected_unless_allowed() -> None:
    definition = assemble_workflow_definition(
        _spec(greeting="Hi {{first_name}}, this is Mia."), "OUTBOUND"
    )
    with pytest.raises(AgentBuilderError, match="template variables"):
        validate_workflow_definition(definition)
    validate_workflow_definition(definition, allow_template_variables=True)


# --- build_agent_workflow -----------------------------------------------------


async def test_build_retries_once_after_bad_output() -> None:
    generator = FakeGenerator(_spec(stage_count=0), _spec())

    generated = await build_agent_workflow(_request(), generator)

    assert len(generator.calls) == 2
    assert generated.name == "Dental Appointment Booker"
    assert generated.as_workflow_data()["workflow_definition"]["nodes"]


async def test_build_retries_template_variables_the_user_did_not_ask_for() -> None:
    generator = FakeGenerator(_spec(greeting="Hi {{name}}."), _spec())
    await build_agent_workflow(_request(), generator)
    assert len(generator.calls) == 2


async def test_build_keeps_template_variables_the_user_asked_for() -> None:
    generator = FakeGenerator(_spec(greeting="Hi {{name}}."))
    request = _request(activity="Greet the patient as {{name}}")
    generated = await build_agent_workflow(request, generator)
    assert len(generator.calls) == 1
    start = _nodes(generated.workflow_definition)["start"]
    assert "{{name}}" in start["data"]["greeting"]


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError(),
        genai_errors.ServerError(503, {"error": {"message": "unavailable"}}),
        AgentBuilderError("The model returned an empty response"),
    ],
)
async def test_build_retries_transient_errors_then_gives_up(error: Exception) -> None:
    generator = FakeGenerator(error, error)

    with pytest.raises(AgentBuilderError, match="Could not generate an agent"):
        await build_agent_workflow(_request(), generator)
    assert len(generator.calls) == 2


@pytest.mark.parametrize(
    "error",
    [_client_error(403), _client_error(400), ValueError("bad credentials json")],
)
async def test_build_does_not_retry_permanent_errors(error: Exception) -> None:
    generator = FakeGenerator(error, _spec())

    with pytest.raises(AgentBuilderError, match="Could not generate an agent"):
        await build_agent_workflow(_request(), generator)
    assert len(generator.calls) == 1


async def test_build_waits_before_retrying_a_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr(agent_builder.asyncio, "sleep", sleep)
    generator = FakeGenerator(_client_error(429), _spec())

    await build_agent_workflow(_request(), generator, rate_limited_delay_secs=1.5)

    sleep.assert_awaited_once_with(1.5)
    assert len(generator.calls) == 2


async def test_build_propagates_missing_platform_configuration() -> None:
    generator = FakeGenerator(PlatformModelsNotConfiguredError("no project"))
    with pytest.raises(PlatformModelsNotConfiguredError):
        await build_agent_workflow(_request(), generator)


async def test_build_falls_back_to_use_case_name() -> None:
    generated = await build_agent_workflow(_request(), FakeGenerator(_spec(name=" ")))
    assert generated.name == "dental clinic agent"


# --- GeminiAgentSpecGenerator -------------------------------------------------

_SETTINGS = PlatformVertexSettings(
    project_id="org-project",
    llm_location="eu",
    realtime_location="europe-west1",
    speech_location="eu",
)


class _FakeModels:
    def __init__(self, text: str | None = None, delay: float = 0.0) -> None:
        self.text = text
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    async def generate_content(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        await asyncio.sleep(self.delay)
        return SimpleNamespace(text=self.text)


def _generator(
    models: _FakeModels, *, timeout_secs: float = 5.0
) -> tuple[GeminiAgentSpecGenerator, list[Any]]:
    seen: list[Any] = []

    async def settings_provider(organization_id: int | None) -> PlatformVertexSettings:
        seen.append(organization_id)
        return _SETTINGS

    def client_factory(settings: PlatformVertexSettings) -> Any:
        seen.append(settings)
        return SimpleNamespace(aio=SimpleNamespace(models=models))

    generator = GeminiAgentSpecGenerator(
        settings_provider=settings_provider,
        client_factory=client_factory,
        model="gemini-test",
        timeout_secs=timeout_secs,
    )
    return generator, seen


async def test_gemini_generator_sends_structured_request() -> None:
    models = _FakeModels(text=_spec().model_dump_json())
    generator, seen = _generator(models)

    spec = await generator.generate(_request(call_type="outbound"))

    assert spec == _spec()
    assert seen == [11, _SETTINGS]  # org placement resolved per request
    call = models.calls[0]
    assert call["model"] == "gemini-test"
    assert "Call direction: OUTBOUND" in call["contents"]
    assert "Book appointments for patients" in call["contents"]
    config = call["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is AgentSpec
    assert config.automatic_function_calling.disable is True


async def test_gemini_generator_rejects_empty_response() -> None:
    generator, _ = _generator(_FakeModels(text=""))
    with pytest.raises(AgentBuilderError, match="empty response"):
        await generator.generate(_request())


async def test_gemini_generator_times_out() -> None:
    generator, _ = _generator(_FakeModels(text="{}", delay=1.0), timeout_secs=0.01)
    with pytest.raises(TimeoutError):
        await generator.generate(_request())


def test_vertex_clients_are_cached_per_placement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            created.append(kwargs)

    monkeypatch.setattr("google.genai.Client", FakeClient)
    monkeypatch.setattr(agent_builder, "_CLIENTS", {})

    first = agent_builder._client_for(_SETTINGS)
    assert agent_builder._client_for(_SETTINGS) is first
    other = PlatformVertexSettings(
        project_id="other",
        llm_location="eu",
        realtime_location="europe-west1",
        speech_location="eu",
    )
    assert agent_builder._client_for(other) is not first
    assert [c["project"] for c in created] == ["org-project", "other"]
    assert created[0]["vertexai"] is True
    assert created[0]["location"] == "eu"


def test_default_generator_builds_without_vertex_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Built on every request, including on servers without platform models,
    # so it must not read settings until it generates.
    monkeypatch.setattr(
        "api.services.configuration.platform.settings.constants.PLATFORM_VERTEX_PROJECT_ID",
        "",
    )
    default_agent_spec_generator()


# --- route --------------------------------------------------------------------


class FakeLimiter:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.keys: list[str] = []

    async def allow(self, key: str, *, limit: int, window: timedelta) -> bool:
        self.keys.append(key)
        return self.allowed


def _make_app(
    generator: FakeGenerator | None = None, limiter: FakeLimiter | None = None
) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=1, provider_id="provider-1", selected_organization_id=11
    )
    rate_limiter = limiter or FakeLimiter()
    app.dependency_overrides[get_rate_limiter] = lambda: rate_limiter
    if generator is not None:
        app.dependency_overrides[workflow_routes.default_agent_spec_generator] = (
            lambda: generator
        )
    return app


_BODY = {
    "call_type": "outbound",
    "use_case": "dental clinic",
    "activity_description": "Remind patients about their appointment",
}


def _created_workflow(**kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        name=kwargs["name"],
        status="active",
        created_at=datetime.now(UTC),
        current_definition_id=7,
        template_context_variables={},
        call_disposition_codes=None,
        workflow_configurations={},
    )


def test_route_generates_locally_when_platform_models_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow_routes.constants, "PLATFORM_MODELS_ENABLED", True)
    generator = FakeGenerator(_spec())
    limiter = FakeLimiter()
    create = AsyncMock(side_effect=_created_workflow)
    mps = AsyncMock()

    with (
        patch.object(workflow_routes.db_client, "create_workflow", create),
        patch.object(workflow_routes.mps_service_key_client, "call_workflow_api", mps),
        patch.object(workflow_routes, "capture_event"),
    ):
        response = TestClient(_make_app(generator, limiter)).post(
            "/workflow/create/template", json=_BODY
        )

    assert response.status_code == 200, response.text
    mps.assert_not_awaited()
    assert generator.calls[0].call_type == "OUTBOUND"
    assert generator.calls[0].organization_id == 11
    assert limiter.keys == ["agent-builder:org:11"]
    assert create.await_args is not None
    kwargs = create.await_args.kwargs
    assert kwargs["name"] == "Dental Appointment Booker"
    assert kwargs["organization_id"] == 11
    validate_workflow_definition(kwargs["workflow_definition"])
    body = response.json()
    assert body["id"] == 42
    assert {n["type"] for n in body["workflow_definition"]["nodes"]} >= {
        "startCall",
        "endCall",
    }


def test_route_uses_mps_when_platform_models_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow_routes.constants, "PLATFORM_MODELS_ENABLED", False)
    generator = FakeGenerator()
    limiter = FakeLimiter()
    mps = AsyncMock(
        return_value={
            "name": "From MPS",
            "workflow_definition": assemble_workflow_definition(_spec(), "INBOUND"),
        }
    )
    create = AsyncMock(side_effect=_created_workflow)

    with (
        patch.object(workflow_routes.db_client, "create_workflow", create),
        patch.object(workflow_routes.mps_service_key_client, "call_workflow_api", mps),
        patch.object(workflow_routes, "capture_event"),
    ):
        response = TestClient(_make_app(generator, limiter)).post(
            "/workflow/create/template", json=_BODY
        )

    assert response.status_code == 200, response.text
    mps.assert_awaited_once()
    assert generator.calls == []
    assert limiter.keys == []
    assert create.await_args is not None
    assert create.await_args.kwargs["name"] == "From MPS"


def test_route_returns_502_when_generation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow_routes.constants, "PLATFORM_MODELS_ENABLED", True)
    generator = FakeGenerator(TimeoutError("boom"), TimeoutError("boom again"))
    create = AsyncMock()

    with patch.object(workflow_routes.db_client, "create_workflow", create):
        response = TestClient(_make_app(generator)).post(
            "/workflow/create/template", json=_BODY
        )

    assert response.status_code == 502
    assert "Could not generate an agent" in response.json()["detail"]
    assert "boom" not in response.json()["detail"]
    create.assert_not_awaited()
    assert len(generator.calls) == 2


def test_route_returns_503_when_vertex_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow_routes.constants, "PLATFORM_MODELS_ENABLED", True)
    generator = FakeGenerator(PlatformModelsNotConfiguredError("no project"))

    response = TestClient(_make_app(generator)).post(
        "/workflow/create/template", json=_BODY
    )

    assert response.status_code == 503
    assert "no project" not in response.json()["detail"]


def test_route_rate_limits_local_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow_routes.constants, "PLATFORM_MODELS_ENABLED", True)
    generator = FakeGenerator(_spec())

    response = TestClient(_make_app(generator, FakeLimiter(allowed=False))).post(
        "/workflow/create/template", json=_BODY
    )

    assert response.status_code == 429
    assert generator.calls == []


@pytest.mark.parametrize(
    "overrides",
    [{"use_case": "x" * 201}, {"activity_description": "x" * 4001}],
)
def test_route_rejects_oversized_input(overrides: dict[str, str]) -> None:
    generator = FakeGenerator()
    response = TestClient(_make_app(generator)).post(
        "/workflow/create/template", json={**_BODY, **overrides}
    )
    assert response.status_code == 422
    assert generator.calls == []
