"""Build a starter agent workflow from a use-case description, on our own Vertex.

The Agent Builder (``POST /workflow/create/template``) used to ask the hosted
MPS service for a workflow. Platform-models deployments never hold an MPS
service key, so there the workflow is generated here instead:

1. An LLM (Gemini on the organization's Vertex placement) writes a small
   structured :class:`AgentSpec` — name, persona, greeting and a few
   conversation stages.
2. :func:`assemble_workflow_definition` turns that spec into ReactFlow
   ``nodes``/``edges`` deterministically, so ids, positions, node types and
   edge wiring never depend on the model.
3. The result goes through the same ``ReactFlowDTO`` + ``WorkflowGraph``
   validation the app runs on save; a transient or bad-output failure is
   retried once.

The LLM sits behind the :class:`AgentSpecGenerator` protocol so tests inject a
fake and never touch the network.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

from google.genai import errors as genai_errors
from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from api.services.configuration.platform.catalog import DEFAULT_LLM_MODEL
from api.services.configuration.platform.policy import (
    platform_settings_for_organization,
)
from api.services.configuration.platform.settings import (
    PlatformModelsNotConfiguredError,
    PlatformVertexSettings,
)
from api.services.workflow.dto import NodeType, ReactFlowDTO
from api.services.workflow.workflow_graph import WorkflowGraph

if TYPE_CHECKING:
    from google import genai

# Main stages after the opening one.
MAX_STAGES: Final = 4
MAX_CAPTURED_FIELDS: Final = 5
GENERATION_ATTEMPTS: Final = 2
GENERATION_TIMEOUT_SECS: Final = 40.0
GENERATION_TEMPERATURE: Final = 0.4
RATE_LIMITED_RETRY_DELAY_SECS: Final = 2.0
# Transition labels become LLM function names, which providers cap at 64.
MAX_TRANSITION_LABEL: Final = 60

# Appended to every generated persona so the agent behaves on a phone line
# whatever the model wrote.
VOICE_RULES: Final = (
    "## Voice rules\n"
    "- This is a phone call. Speak in short, natural sentences, one or two at "
    "a time.\n"
    "- Never use lists, markdown, emojis or special characters; they cannot "
    "be spoken.\n"
    "- Ask one question at a time and wait for the answer.\n"
    "- Transcripts can contain errors. If something is unclear, politely ask the "
    "caller to repeat it.\n"
    "- Read numbers, dates and email addresses back slowly to confirm them.\n"
    "- Never invent facts, prices or policies. If you do not know, say so and "
    "offer a follow-up."
)

EARLY_EXIT_PROMPT: Final = (
    "The call is ending early. Do not confirm, book or promise anything. "
    "Briefly acknowledge what the person said, thank them for their time, "
    "and say a short, polite goodbye."
)

_CANVAS_X: Final = 175.0
_EARLY_EXIT_X: Final = 625.0
_ROW_HEIGHT: Final = 220.0
_GLOBAL_X: Final = -325.0
_IDENTIFIER_RE: Final = re.compile(r"[^a-z0-9]+")
_TEMPLATE_MARKER: Final = "{{"


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
        description=(
            f"The main conversation stages in order, 1 to {MAX_STAGES} of them."
        ),
    )
    closing_prompt: str = Field(
        description=(
            "How to wrap up after the last stage succeeds: summarise next steps, "
            "thank the caller, say goodbye."
        )
    )
    end_call_when: str = Field(
        description=(
            "When the call should end early from any stage, e.g. the caller asks "
            "to stop, is not interested, or it is a wrong number."
        )
    )
    captured_fields: list[CapturedFieldSpec] = Field(
        description=f"Up to {MAX_CAPTURED_FIELDS} facts worth recording.",
    )


@dataclass(frozen=True, slots=True)
class AgentBuilderRequest:
    # "INBOUND" or "OUTBOUND" (case-insensitive).
    call_type: str
    use_case: str
    activity_description: str
    # Whose Vertex placement to generate on; None uses the server defaults.
    organization_id: int | None = None

    @property
    def is_outbound(self) -> bool:
        return self.call_type.upper() == "OUTBOUND"


@dataclass(frozen=True, slots=True)
class GeneratedWorkflow:
    name: str
    workflow_definition: dict[str, Any]

    def as_workflow_data(self) -> dict[str, Any]:
        """The shape the MPS workflow API returns, which the route consumes."""
        return {"name": self.name, "workflow_definition": self.workflow_definition}


class AgentSpecGenerator(Protocol):
    async def generate(self, request: AgentBuilderRequest) -> AgentSpec: ...


SettingsProvider = Callable[[int | None], Awaitable[PlatformVertexSettings]]


# --- Gemini on Vertex ---------------------------------------------------------

_SYSTEM_INSTRUCTION: Final = f"""\
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
- Split the conversation into an opening stage plus 1 to {MAX_STAGES} focused \
stages. Each stage prompt covers one goal, and its done_when condition is a \
concrete, observable event in the conversation.
- end_call_when must cover every way the call can finish early from any \
stage: for example the person is busy and wants a call back, is not \
interested, asks to stop, or it is a wrong number.
- List at most {MAX_CAPTURED_FIELDS} captured_fields.
- Do not use template variables, curly braces or placeholders such as \
[Company]. If a company or person name is not given, describe the role \
generically ("our team", "the clinic").
- Do not promise actions the agent cannot perform on the call itself (such as \
sending emails or texts) unless the description says it can; offer that the \
team will follow up instead.
- Keep the language of the description; default to English.
"""

# One client per Vertex placement: each client owns an HTTP connection pool,
# so building one per request would leak pools.
_CLIENTS: dict[tuple[str, str, str | None], genai.Client] = {}


def _client_for(settings: PlatformVertexSettings) -> genai.Client:
    key = (settings.project_id, settings.llm_location, settings.credentials_json)
    client = _CLIENTS.get(key)
    if client is None:
        from google import genai

        client = genai.Client(
            vertexai=True,
            project=settings.project_id,
            location=settings.llm_location,
            credentials=_vertex_credentials(settings.credentials_json),
        )
        _CLIENTS[key] = client
    return client


class GeminiAgentSpecGenerator:
    """Generates an :class:`AgentSpec` with Gemini on the org's Vertex placement."""

    def __init__(
        self,
        *,
        settings_provider: SettingsProvider = platform_settings_for_organization,
        client_factory: Callable[[PlatformVertexSettings], genai.Client] = _client_for,
        model: str = DEFAULT_LLM_MODEL,
        timeout_secs: float = GENERATION_TIMEOUT_SECS,
    ) -> None:
        self._settings_provider = settings_provider
        self._client_factory = client_factory
        self._model = model
        self._timeout_secs = timeout_secs

    async def generate(self, request: AgentBuilderRequest) -> AgentSpec:
        from google.genai import types

        # Resolved per call: an Enterprise org may pin its own project/region.
        settings = await self._settings_provider(request.organization_id)
        client = self._client_factory(settings)
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
            client.aio.models.generate_content(
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
    direction = "OUTBOUND" if request.is_outbound else "INBOUND"
    return (
        f"Call direction: {direction}\n"
        f"Use case: {request.use_case.strip()}\n"
        f"What the agent should do: {request.activity_description.strip()}"
    )


def default_agent_spec_generator() -> AgentSpecGenerator:
    """The production generator (FastAPI dependency).

    Cheap to build: nothing is read or connected until the first generation,
    so it is safe on servers without platform models.
    """
    return GeminiAgentSpecGenerator()


# --- Deterministic assembly ---------------------------------------------------


def assemble_workflow_definition(spec: AgentSpec, call_type: str) -> dict[str, Any]:
    """Turn an :class:`AgentSpec` into a ReactFlow workflow definition.

    Layout: Start -> stage 1 -> ... -> stage N -> End, each step advancing on
    its ``done_when`` condition. Every step also has an "End Call" edge to a
    separate early-exit end node that only says goodbye, so an early hang-up
    never reuses the success summary. The captured fields are extracted on
    every prompted node, because the engine extracts on leaving a node and on
    the node the call ends in: wherever the call stops, they are recorded.

    Raises AgentBuilderError when the spec is unusable (e.g. empty text).
    """
    opening_prompt = _required(spec.opening.prompt, "opening.prompt")
    stages = [stage for stage in spec.stages if stage.prompt.strip()][:MAX_STAGES]
    if not stages:
        raise AgentBuilderError("The generated agent has no conversation stages")

    outbound = call_type.upper() == "OUTBOUND"
    direction = (
        "This is an OUTBOUND call: you called the customer."
        if outbound
        else "This is an INBOUND call: the customer called you."
    )
    extraction = _extraction(spec.captured_fields)

    start_id, end_id, early_id, global_id = "start", "end", "end_early", "global"
    stage_ids = [f"stage_{index}" for index in range(1, len(stages) + 1)]

    nodes: list[dict[str, Any]] = [
        _node(
            start_id,
            NodeType.startNode,
            row=0,
            data={
                "name": _title(spec.opening.name, "Greeting"),
                "prompt": opening_prompt,
                "greeting": _required(spec.greeting, "greeting"),
                "greeting_type": "text",
                "is_start": True,
                # Outbound: the callee often talks over the greeting
                # ("who is this?"), so let them.
                "allow_interrupt": outbound,
                "add_global_prompt": True,
                **extraction,
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
                    **extraction,
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
                **extraction,
            },
        )
    )
    nodes.append(
        _node(
            early_id,
            NodeType.endNode,
            row=len(stages) + 1,
            x=_EARLY_EXIT_X,
            data={
                "name": "Polite Goodbye",
                "prompt": EARLY_EXIT_PROMPT,
                "is_end": True,
                "allow_interrupt": False,
                "add_global_prompt": True,
                **extraction,
            },
        )
    )
    persona = _required(spec.persona, "persona")
    nodes.append(
        _node(
            global_id,
            NodeType.globalNode,
            row=0,
            x=_GLOBAL_X,
            data={
                "name": "Global Node",
                "prompt": f"{persona}\n\n{direction}\n\n{VOICE_RULES}",
            },
        )
    )

    end_when = _required(spec.end_call_when, "end_call_when")
    chain = [(start_id, spec.opening), *zip(stage_ids, stages, strict=True)]
    edges: list[dict[str, Any]] = []
    for index, (source, stage) in enumerate(chain):
        done_when = _required(stage.done_when, "done_when")
        if index == len(chain) - 1:
            edges.append(
                _edge(source, end_id, label="Finish Call", condition=done_when)
            )
        else:
            target, target_stage = chain[index + 1]
            edges.append(
                _edge(
                    source,
                    target,
                    label=_transition_label(target_stage.name, index + 1),
                    condition=done_when,
                )
            )
        edges.append(_edge(source, early_id, label="End Call", condition=end_when))

    return {"nodes": nodes, "edges": edges, "viewport": {"x": 0, "y": 0, "zoom": 0.75}}


def validate_workflow_definition(
    definition: dict[str, Any], *, allow_template_variables: bool = False
) -> None:
    """Run the app's own workflow validation; raise AgentBuilderError on failure.

    Unless *allow_template_variables*, a definition that needs ``{{variables}}``
    is rejected: nothing would fill them on a test call.
    """
    try:
        graph = WorkflowGraph(ReactFlowDTO.model_validate(definition))
    except (ValidationError, ValueError) as exc:
        raise AgentBuilderError(f"Generated workflow is invalid: {exc}") from exc
    required = graph.get_required_template_variables()
    if required and not allow_template_variables:
        raise AgentBuilderError(
            f"Generated workflow uses template variables: {sorted(required)}"
        )


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, ValidationError | AgentBuilderError | TimeoutError):
        return True
    if isinstance(exc, genai_errors.ServerError):
        return True
    return isinstance(exc, genai_errors.ClientError) and exc.code == 429


async def build_agent_workflow(
    request: AgentBuilderRequest,
    generator: AgentSpecGenerator,
    *,
    attempts: int = GENERATION_ATTEMPTS,
    rate_limited_delay_secs: float = RATE_LIMITED_RETRY_DELAY_SECS,
) -> GeneratedWorkflow:
    """Generate, assemble and validate a workflow.

    Bad model output, timeouts, server errors and 429s are retried; anything
    else (credentials, configuration, other 4xx) fails at once. Raises
    AgentBuilderError with a user-facing message, or
    PlatformModelsNotConfiguredError when the server cannot reach Vertex.
    """
    allow_variables = _TEMPLATE_MARKER in (
        request.use_case + request.activity_description
    )
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            spec = await generator.generate(request)
            definition = assemble_workflow_definition(spec, request.call_type)
            validate_workflow_definition(
                definition, allow_template_variables=allow_variables
            )
        except PlatformModelsNotConfiguredError:
            raise
        except Exception as exc:  # noqa: BLE001 — classified just below
            last_error = exc
            logger.warning(
                f"Agent builder attempt {attempt}/{attempts} failed: "
                f"{type(exc).__name__}: {exc}"
            )
            if not _is_retryable(exc):
                break
            if (
                attempt < attempts
                and isinstance(exc, genai_errors.ClientError)
                and exc.code == 429
            ):
                await asyncio.sleep(rate_limited_delay_secs)
            continue
        name = _title(spec.name, f"{request.use_case.strip()} agent")[:120]
        return GeneratedWorkflow(name=name, workflow_definition=definition)
    raise AgentBuilderError(
        "Could not generate an agent from this description. Please try again, "
        "or start from a blank canvas."
    ) from last_error


# --- helpers ------------------------------------------------------------------


def _node(
    node_id: str,
    node_type: NodeType,
    *,
    row: int,
    data: dict[str, Any],
    x: float = _CANVAS_X,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type.value,
        "position": {"x": x, "y": row * _ROW_HEIGHT},
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


def _transition_label(stage_name: str, step: int) -> str:
    prefix = "Go to "
    name = _title(stage_name, f"Step {step}")[: MAX_TRANSITION_LABEL - len(prefix)]
    return prefix + name.rstrip()


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
        "extraction_prompt": (
            "Extract these details from the whole conversation so far. Leave a "
            "value empty if it has not been mentioned yet."
        ),
        "extraction_variables": variables,
    }


def _title(value: str, fallback: str) -> str:
    return " ".join(value.split())[:60] or fallback


def _required(value: str, field: str) -> str:
    text = value.strip()
    if not text:
        raise AgentBuilderError(f"The generated agent is missing {field}")
    return text
