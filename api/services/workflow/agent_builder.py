"""Build a starter agent workflow from a use-case description, on our own Vertex.

The Agent Builder (``POST /workflow/create/template``) used to ask the hosted
MPS service for a workflow. Platform-models deployments never hold an MPS
service key, so there the workflow is generated here instead:

1. An LLM (Gemini on the operator's Vertex project) writes a small structured
   :class:`AgentSpec` — name, persona, greeting and a few conversation stages.
2. :func:`assemble_workflow_definition` turns that spec into ReactFlow
   ``nodes``/``edges`` deterministically, so ids, positions, node types and
   edge wiring never depend on the model.
3. The result goes through the same ``ReactFlowDTO`` + ``WorkflowGraph``
   validation the app runs on save; a failed attempt is retried once.

The LLM sits behind the :class:`AgentSpecGenerator` protocol so tests inject a
fake and never touch the network.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from api.services.configuration.platform.catalog import DEFAULT_LLM_MODEL
from api.services.configuration.platform.settings import (
    PlatformVertexSettings,
    load_platform_vertex_settings,
)
from api.services.workflow.dto import NodeType, ReactFlowDTO
from api.services.workflow.workflow_graph import WorkflowGraph

if TYPE_CHECKING:
    from google import genai

MAX_STAGES: Final = 5
MAX_CAPTURED_FIELDS: Final = 6
GENERATION_ATTEMPTS: Final = 2
GENERATION_TIMEOUT_SECS: Final = 60.0
GENERATION_TEMPERATURE: Final = 0.4

# Appended to every generated persona so the agent behaves on a phone line
# whatever the model wrote.
VOICE_RULES: Final = (
    "## Voice rules\n"
    "- This is a phone call. Speak in short, natural sentences, one or two at a time.\n"
    "- Never use lists, markdown, emojis or special characters; they cannot "
    "be spoken.\n"
    "- Ask one question at a time and wait for the answer.\n"
    "- Transcripts can contain errors. If something is unclear, politely ask the "
    "caller to repeat it.\n"
    "- Read numbers, dates and email addresses back slowly to confirm them.\n"
    "- Never invent facts, prices or policies. If you do not know, say so and "
    "offer a follow-up."
)

_CANVAS_X: Final = 175.0
_ROW_HEIGHT: Final = 220.0
_GLOBAL_X: Final = -325.0
_IDENTIFIER_RE: Final = re.compile(r"[^a-z0-9]+")


class AgentBuilderError(RuntimeError):
    """The workflow could not be generated (LLM failure or unusable output)."""


# --- What the LLM returns -----------------------------------------------------
# Kept flat and constraint-free: Gemini's structured output accepts this schema
# as-is, and the limits that matter are enforced in code below.


class StageSpec(BaseModel):
    name: str = Field(
        description="Short stage title, 2-4 words, e.g. 'Collect details'."
    )
    prompt: str = Field(
        description=(
            "Instructions for the agent during this stage only: goal, what to say "
            "or ask, how to handle common answers. Plain prose, voice friendly."
        )
    )
    done_when: str = Field(
        description=(
            "One sentence describing when this stage is complete and the "
            "conversation should move on, e.g. 'The caller has confirmed their "
            "appointment date and time.'"
        )
    )


class CapturedFieldSpec(BaseModel):
    name: str = Field(description="snake_case variable name, e.g. 'preferred_date'.")
    description: str = Field(description="What to extract from the conversation.")


class AgentSpec(BaseModel):
    name: str = Field(description="Agent name for the dashboard, 2-6 words.")
    persona: str = Field(
        description=(
            "Who the agent is, who it represents, its tone, and the overall goal "
            "of the call. Second person ('You are ...')."
        )
    )
    greeting: str = Field(
        description=(
            "The first sentence the agent speaks when the call connects. For "
            "outbound calls, introduce yourself and the reason for calling."
        )
    )
    opening: StageSpec = Field(
        description="The opening stage right after the greeting.",
    )
    stages: list[StageSpec] = Field(
        description="The main conversation stages in order, 1 to 4 of them.",
    )
    closing_prompt: str = Field(
        description=(
            "How to wrap up: summarise next steps, thank the caller, say goodbye."
        )
    )
    end_call_when: str = Field(
        description=(
            "When the call should end early from any stage, e.g. the caller asks "
            "to stop, is not interested, or it is a wrong number."
        )
    )
    captured_fields: list[CapturedFieldSpec] = Field(
        description="Up to 5 facts worth recording after the call.",
    )


@dataclass(frozen=True, slots=True)
class AgentBuilderRequest:
    # "INBOUND" or "OUTBOUND" (case-insensitive).
    call_type: str
    use_case: str
    activity_description: str


@dataclass(frozen=True, slots=True)
class GeneratedWorkflow:
    name: str
    workflow_definition: dict[str, Any]

    def as_workflow_data(self) -> dict[str, Any]:
        """The shape the MPS workflow API returns, which the route consumes."""
        return {"name": self.name, "workflow_definition": self.workflow_definition}


class AgentSpecGenerator(Protocol):
    async def generate(self, request: AgentBuilderRequest) -> AgentSpec: ...


# --- Gemini on Vertex ---------------------------------------------------------

_SYSTEM_INSTRUCTION: Final = """\
You design voice AI phone agents. Given a call direction, a use case and a \
description of what the agent should do, write a concise, realistic plan for \
the agent as JSON matching the schema.

Guidelines:
- The agent speaks on a phone call, so every prompt must produce short, \
spoken-style replies. No markdown, lists or special characters in anything \
the agent will say.
- INBOUND: the customer called the business. Greet warmly and ask how you \
can help or confirm why they are calling.
- OUTBOUND: the agent is calling the customer. Introduce yourself and the \
company, state the reason for the call, and check it is a good time before \
going further.
- Split the conversation into an opening stage plus 1 to 4 focused stages. \
Each stage prompt covers one goal, and its done_when condition is a concrete, \
observable event in the conversation.
- end_call_when must cover every way the call can finish early from any \
stage: for example the person is busy and wants a call back, is not \
interested, asks to stop, or it is a wrong number.
- Do not use template variables, curly braces or placeholders such as \
[Company]. If a company or person name is not given, describe the role \
generically ("our team", "the clinic").
- Do not promise actions the agent cannot perform on the call itself (such as \
sending emails or texts) unless the description says it can; offer that the \
team will follow up instead.
- Keep the language of the description; default to English.
"""


class GeminiAgentSpecGenerator:
    """Generates an :class:`AgentSpec` with Gemini on the operator's Vertex project."""

    def __init__(
        self,
        settings: PlatformVertexSettings | None = None,
        *,
        model: str = DEFAULT_LLM_MODEL,
        timeout_secs: float = GENERATION_TIMEOUT_SECS,
    ) -> None:
        self._settings = settings
        self._model = model
        self._timeout_secs = timeout_secs
        self._client: genai.Client | None = None

    def _get_client(self) -> genai.Client:
        if self._client is None:
            from google import genai

            # Settings load lazily so building the generator never fails on a
            # server without platform models (the route only uses it there).
            settings = self._settings or load_platform_vertex_settings()
            self._client = genai.Client(
                vertexai=True,
                project=settings.project_id,
                location=settings.llm_location,
                credentials=_vertex_credentials(settings.credentials_json),
            )
        return self._client

    async def generate(self, request: AgentBuilderRequest) -> AgentSpec:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=_SYSTEM_INSTRUCTION,
            temperature=GENERATION_TEMPERATURE,
            response_mime_type="application/json",
            response_schema=AgentSpec,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )
        response = await asyncio.wait_for(
            self._get_client().aio.models.generate_content(
                model=self._model, contents=_user_message(request), config=config
            ),
            self._timeout_secs,
        )
        if not response.text:
            raise AgentBuilderError("The model returned an empty response")
        return AgentSpec.model_validate_json(response.text)


def _vertex_credentials(credentials_json: str | None) -> Any:
    """Service-account credentials from JSON, or None for Application Default."""
    if not credentials_json:
        return None
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
        json.loads(credentials_json),
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )


def _user_message(request: AgentBuilderRequest) -> str:
    return (
        f"Call direction: {request.call_type}\n"
        f"Use case: {request.use_case.strip()}\n"
        f"What the agent should do: {request.activity_description.strip()}"
    )


def default_agent_spec_generator() -> AgentSpecGenerator:
    """The production generator, on the platform's Vertex settings.

    Cheap to build: nothing is read or connected until the first generation.
    """
    return GeminiAgentSpecGenerator()


# --- Deterministic assembly ---------------------------------------------------


def assemble_workflow_definition(spec: AgentSpec, call_type: str) -> dict[str, Any]:
    """Turn an :class:`AgentSpec` into a ReactFlow workflow definition.

    Layout: Start -> stage 1 -> ... -> stage N -> End, each stage advancing on
    its ``done_when`` condition, plus an "End Call" edge from every non-final
    step for early exits. The global node carries the persona and voice rules.

    Raises AgentBuilderError when the spec is unusable (e.g. empty text).
    """
    opening_prompt = _required(spec.opening.prompt, "opening.prompt")
    stages = [stage for stage in spec.stages if stage.prompt.strip()][:MAX_STAGES]
    if not stages:
        raise AgentBuilderError("The generated agent has no conversation stages")

    start_id = "start"
    stage_ids = [f"stage_{index}" for index in range(1, len(stages) + 1)]
    end_id = "end"
    global_id = "global"

    direction = (
        "This is an OUTBOUND call: you called the customer."
        if call_type.upper() == "OUTBOUND"
        else "This is an INBOUND call: the customer called you."
    )
    nodes: list[dict[str, Any]] = [
        _node(
            start_id,
            NodeType.startNode,
            row=0,
            data={
                "name": _title(spec.opening.name, "Greeting"),
                "prompt": f"{direction}\n\n{opening_prompt}",
                "greeting": _required(spec.greeting, "greeting"),
                "greeting_type": "text",
                "is_start": True,
                "allow_interrupt": False,
                "add_global_prompt": True,
                "extraction_enabled": False,
            },
        )
    ]
    for row, (node_id, stage) in enumerate(zip(stage_ids, stages, strict=True), 1):
        nodes.append(
            _node(
                node_id,
                NodeType.agentNode,
                row=row,
                data={
                    "name": _title(stage.name, f"Step {row}"),
                    "prompt": stage.prompt.strip(),
                    "allow_interrupt": True,
                    "add_global_prompt": True,
                    "extraction_enabled": False,
                },
            )
        )
    nodes.append(
        _node(
            end_id,
            NodeType.endNode,
            row=len(stages) + 1,
            data={
                "name": "End Call",
                "prompt": _required(spec.closing_prompt, "closing_prompt"),
                "is_end": True,
                "allow_interrupt": False,
                "add_global_prompt": True,
                **_extraction(spec.captured_fields),
            },
        )
    )
    nodes.append(
        {
            "id": global_id,
            "type": NodeType.globalNode.value,
            "position": {"x": _GLOBAL_X, "y": 0.0},
            "data": {
                "name": "Global Node",
                "prompt": f"{_required(spec.persona, 'persona')}\n\n{VOICE_RULES}",
            },
        }
    )

    end_when = _required(spec.end_call_when, "end_call_when")
    chain = [(start_id, spec.opening), *zip(stage_ids, stages, strict=True)]
    edges: list[dict[str, Any]] = []
    for index, (source, stage) in enumerate(chain):
        is_last = index == len(chain) - 1
        if is_last:
            edges.append(
                _edge(
                    source,
                    end_id,
                    label="Finish Call",
                    condition=(f"{stage.done_when.strip()} Also end when: {end_when}"),
                )
            )
            continue
        target, target_stage = chain[index + 1]
        edges.append(
            _edge(
                source,
                target,
                label=f"Go to {_title(target_stage.name, f'Step {index + 1}')}",
                condition=_required(stage.done_when, "done_when"),
            )
        )
        edges.append(_edge(source, end_id, label="End Call", condition=end_when))

    return {"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 0.75}}


def validate_workflow_definition(definition: dict[str, Any]) -> None:
    """Run the app's own workflow validation; raise AgentBuilderError on failure."""
    try:
        WorkflowGraph(ReactFlowDTO.model_validate(definition))
    except (ValidationError, ValueError) as exc:
        raise AgentBuilderError(f"Generated workflow is invalid: {exc}") from exc


async def build_agent_workflow(
    request: AgentBuilderRequest,
    generator: AgentSpecGenerator,
    *,
    attempts: int = GENERATION_ATTEMPTS,
) -> GeneratedWorkflow:
    """Generate, assemble and validate a workflow, retrying a failed attempt."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            spec = await generator.generate(request)
            definition = assemble_workflow_definition(spec, request.call_type)
            validate_workflow_definition(definition)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — any failure earns one retry
            last_error = exc
            logger.warning(
                f"Agent builder attempt {attempt}/{attempts} failed: "
                f"{type(exc).__name__}: {exc}"
            )
            continue
        name = _title(spec.name, f"{request.use_case.strip()} agent")[:120]
        return GeneratedWorkflow(name=name, workflow_definition=definition)
    raise AgentBuilderError(
        "Could not generate an agent from this description. Please try again, "
        "or start from a blank canvas."
    ) from last_error


# --- helpers ------------------------------------------------------------------


def _node(
    node_id: str, node_type: NodeType, *, row: int, data: dict[str, Any]
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type.value,
        "position": {"x": _CANVAS_X, "y": row * _ROW_HEIGHT},
        "data": data,
    }


def _edge(source: str, target: str, *, label: str, condition: str) -> dict[str, Any]:
    return {
        "id": f"{source}-{target}",
        "source": source,
        "target": target,
        "type": "custom",
        "animated": True,
        "data": {"label": label, "condition": condition},
    }


def _extraction(fields: list[CapturedFieldSpec]) -> dict[str, Any]:
    variables: list[dict[str, str]] = []
    seen: set[str] = set()
    for field in fields:
        name = _IDENTIFIER_RE.sub("_", field.name.lower()).strip("_")
        if not name or name in seen or not field.description.strip():
            continue
        seen.add(name)
        variables.append(
            {"name": name, "type": "string", "prompt": field.description.strip()}
        )
        if len(variables) == MAX_CAPTURED_FIELDS:
            break
    if not variables:
        return {"extraction_enabled": False}
    return {
        "extraction_enabled": True,
        "extraction_prompt": "Extract these details from the conversation.",
        "extraction_variables": variables,
    }


def _title(value: str, fallback: str) -> str:
    return " ".join(value.split())[:60] or fallback


def _required(value: str, field: str) -> str:
    text = value.strip()
    if not text:
        raise AgentBuilderError(f"The generated agent is missing {field}")
    return text
