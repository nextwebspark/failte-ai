"""Tests for the local Agent Builder used when platform models are enabled."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import workflow as workflow_routes
from api.routes.workflow import router
from api.services.auth.depends import get_user
from api.services.workflow.agent_builder import (
    AgentBuilderError,
    AgentBuilderRequest,
    AgentSpec,
    CapturedFieldSpec,
    StageSpec,
    assemble_workflow_definition,
    build_agent_workflow,
    default_agent_spec_generator,
    validate_workflow_definition,
)
from api.services.workflow.dto import ReactFlowDTO
from api.services.workflow.workflow_graph import WorkflowGraph


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


def _request(call_type: str = "INBOUND") -> AgentBuilderRequest:
    return AgentBuilderRequest(
        call_type=call_type,
        use_case="dental clinic",
        activity_description="Book appointments for patients",
    )


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
    nodes = {node["id"]: node for node in definition["nodes"]}
    types = [node["type"] for node in definition["nodes"]]

    assert types == ["startCall", "agentNode", "agentNode", "endCall", "globalNode"]
    start = nodes["start"]["data"]
    assert start["greeting"] == "Hello, thanks for calling the clinic. This is Mia."
    assert start["greeting_type"] == "text"
    assert start["is_start"] is True
    assert nodes["end"]["data"]["is_end"] is True
    assert "## Voice rules" in nodes["global"]["data"]["prompt"]

    # Extraction variables are snake_cased and de-duplicated.
    end = nodes["end"]["data"]
    assert end["extraction_enabled"] is True
    assert [v["name"] for v in end["extraction_variables"]] == [
        "preferred_date",
        "patient_name",
    ]

    edges = {(edge["source"], edge["target"]) for edge in definition["edges"]}
    assert edges == {
        ("start", "stage_1"),
        ("start", "end"),
        ("stage_1", "stage_2"),
        ("stage_1", "end"),
        ("stage_2", "end"),
    }
    assert len({edge["id"] for edge in definition["edges"]}) == len(edges)
    for edge in definition["edges"]:
        assert edge["source"] in nodes and edge["target"] in nodes
        assert edge["data"]["label"] and edge["data"]["condition"]
    # Every node except the global one is reachable from the start node.
    reachable, frontier = {"start"}, ["start"]
    while frontier:
        source = frontier.pop()
        for edge in definition["edges"]:
            if edge["source"] == source and edge["target"] not in reachable:
                reachable.add(edge["target"])
                frontier.append(edge["target"])
    assert reachable == set(nodes) - {"global"}


@pytest.mark.parametrize(
    ("call_type", "expected"),
    [
        ("INBOUND", "INBOUND call"),
        ("OUTBOUND", "OUTBOUND call"),
        ("outbound", "OUTBOUND call"),
    ],
)
def test_start_prompt_reflects_call_type(call_type: str, expected: str) -> None:
    definition = assemble_workflow_definition(_spec(), call_type)
    start = next(node for node in definition["nodes"] if node["id"] == "start")
    assert expected in start["data"]["prompt"]


def test_stages_are_capped_and_no_extraction_without_fields() -> None:
    definition = assemble_workflow_definition(
        _spec(stage_count=9, captured_fields=[]), "INBOUND"
    )
    validate_workflow_definition(definition)
    agent_nodes = [n for n in definition["nodes"] if n["type"] == "agentNode"]
    assert len(agent_nodes) == 5
    end = next(n for n in definition["nodes"] if n["type"] == "endCall")
    assert end["data"]["extraction_enabled"] is False


def test_spec_without_stages_is_rejected() -> None:
    with pytest.raises(AgentBuilderError):
        assemble_workflow_definition(_spec(stage_count=0), "INBOUND")


def test_blank_greeting_is_rejected() -> None:
    with pytest.raises(AgentBuilderError):
        assemble_workflow_definition(_spec(greeting="   "), "INBOUND")


# --- build_agent_workflow -----------------------------------------------------


async def test_build_retries_once_after_a_failure() -> None:
    generator = FakeGenerator(ValueError("bad json"), _spec())

    generated = await build_agent_workflow(_request(), generator)

    assert len(generator.calls) == 2
    assert generated.name == "Dental Appointment Booker"
    assert generated.as_workflow_data()["workflow_definition"]["nodes"]


async def test_build_retries_invalid_spec_then_gives_up() -> None:
    generator = FakeGenerator(_spec(stage_count=0), RuntimeError("timeout"))

    with pytest.raises(AgentBuilderError, match="Could not generate an agent"):
        await build_agent_workflow(_request(), generator)
    assert len(generator.calls) == 2


async def test_build_falls_back_to_use_case_name() -> None:
    generated = await build_agent_workflow(_request(), FakeGenerator(_spec(name=" ")))
    assert generated.name == "dental clinic agent"


def test_default_generator_builds_without_vertex_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Constructed on every request, including on servers without platform
    # models, so it must not read settings until it generates.
    monkeypatch.setattr(
        "api.services.configuration.platform.settings.constants.PLATFORM_VERTEX_PROJECT_ID",
        "",
    )
    default_agent_spec_generator()


# --- route --------------------------------------------------------------------


def _make_app(generator: FakeGenerator | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user] = lambda: SimpleNamespace(
        id=1, provider_id="provider-1", selected_organization_id=11
    )
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
    create = AsyncMock(side_effect=_created_workflow)
    mps = AsyncMock()

    with (
        patch.object(workflow_routes.db_client, "create_workflow", create),
        patch.object(workflow_routes.mps_service_key_client, "call_workflow_api", mps),
        patch.object(workflow_routes, "capture_event"),
    ):
        response = TestClient(_make_app(generator)).post(
            "/workflow/create/template", json=_BODY
        )

    assert response.status_code == 200, response.text
    mps.assert_not_awaited()
    assert generator.calls[0].call_type == "OUTBOUND"
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
        response = TestClient(_make_app(generator)).post(
            "/workflow/create/template", json=_BODY
        )

    assert response.status_code == 200, response.text
    mps.assert_awaited_once()
    assert generator.calls == []
    assert create.await_args is not None
    assert create.await_args.kwargs["name"] == "From MPS"


def test_route_returns_502_when_generation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workflow_routes.constants, "PLATFORM_MODELS_ENABLED", True)
    generator = FakeGenerator(RuntimeError("boom"), RuntimeError("boom again"))
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
