"""Fast router: a light model acknowledges the caller while the main LLM works.

At the end of each user turn the user aggregator pushes an ``LLMContextFrame``
to the main LLM. ``FastRouterProcessor`` sits just before the main LLM: it
forwards that frame untouched, so the main LLM starts immediately, and in
parallel asks a light model to classify the turn and write a short spoken
acknowledgement ("Sure, one moment.").

The acknowledgement cannot travel through the main LLM: the LLM handles a
context frame inline, so anything queued behind it would be spoken after the
answer. ``AckGate`` therefore sits just before TTS and speaks the
acknowledgement itself, but only if no text from the main LLM has reached TTS
for that turn yet, so an acknowledgement never cuts into an answer.

The router never answers, books, or transitions: the main LLM keeps full
control of the conversation. The acknowledgement is not added to the LLM
context; the main LLM's prompt is told one has usually been spoken.
"""

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from loguru import logger

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InterruptionFrame,
    LLMContextFrame,
    LLMTextFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

DEFAULT_ROUTER_PROMPT = """You are the fast front desk of a phone agent. You never answer the caller.
For the caller's latest turn, return JSON only:
{"route": a short label for what the caller wants, "ack": a natural spoken acknowledgement of
at most 6 words, or ""}
The ack is spoken immediately while the agent prepares the real answer. Never state a fact,
price, time or number, and never promise anything. Return "" when the caller is only
answering yes or no, giving personal details, or saying goodbye."""

_MAX_ACK_WORDS = 8
_NO_ACK_ROUTES = {"end_call"}
# An acknowledgement must never carry a figure: prices, times and numbers belong
# to the main LLM, which has the tool results.
_FORBIDDEN_IN_ACK = re.compile(r"[0-9€$£%]")


@dataclass
class RouterDecision:
    """A light model's verdict on one caller turn."""

    route: str
    ack: str


DecideFn = Callable[[str], Awaitable[RouterDecision | None]]


def transcript_from_messages(messages: list, limit: int) -> str:
    """Render the last ``limit`` spoken messages as ``Caller:`` / ``Agent:`` lines."""
    lines = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in (
            "user",
            "assistant",
        ):
            continue
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type", "text") == "text"
            )
        text = (content or "").strip() if isinstance(content, str) else ""
        if text:
            lines.append(
                f"{'Caller' if message['role'] == 'user' else 'Agent'}: {text}"
            )
    return "\n".join(lines[-limit:])


def safe_ack(decision: RouterDecision) -> str:
    """Return the acknowledgement to speak, or "" if it must not be spoken."""
    ack = (decision.ack or "").strip().strip('"').strip()
    if not ack or decision.route in _NO_ACK_ROUTES:
        return ""
    if _FORBIDDEN_IN_ACK.search(ack) or len(ack.split()) > _MAX_ACK_WORDS:
        return ""
    return ack


class AckGate(FrameProcessor):
    """Speaks a router acknowledgement unless the turn's own speech has started.

    Placed directly before TTS. Each user turn is opened with :meth:`begin_turn`;
    an acknowledgement offered for that turn is spoken only while no LLM text
    (or engine speech) has passed through the gate since the turn began.

    One filler per turn: once the acknowledgement has been spoken, engine speech
    that is not part of the answer (``append_to_context=False``, such as a
    tool's "let me check" line) is dropped until the LLM's own text arrives.
    When the router stayed silent, that line plays as usual.
    """

    def __init__(self, **kwargs):
        """Initialize the gate.

        Args:
            **kwargs: Additional arguments passed to FrameProcessor.
        """
        super().__init__(**kwargs)
        self._turn = 0
        self._speech_started = False
        self._llm_text_started = False
        self._acked = False

    def begin_turn(self) -> int:
        """Start a new user turn and return its id."""
        self._turn += 1
        self._speech_started = False
        self._llm_text_started = False
        self._acked = False
        return self._turn

    async def offer(self, turn: int, text: str) -> str:
        """Speak ``text`` if it is still useful for ``turn``; return the outcome."""
        if turn != self._turn:
            return "stale"
        if self._speech_started:
            return "late"
        if self._acked:
            return "duplicate"
        self._acked = True
        await self.push_frame(
            TTSSpeakFrame(text, append_to_context=False, persist_to_logs=True)
        )
        return "spoken"

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Track the turn's speech, drop a second filler, pass everything else."""
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, LLMTextFrame):
                self._speech_started = True
                self._llm_text_started = True
            elif isinstance(frame, TTSSpeakFrame):
                if (
                    self._acked
                    and not self._llm_text_started
                    and not frame.append_to_context
                ):
                    logger.info(
                        f"{self}: dropped {frame.text!r}; "
                        "the router already acknowledged this turn"
                    )
                    return
                self._speech_started = True
        await self.push_frame(frame, direction)


class FastRouterProcessor(FrameProcessor):
    """Asks a light model for an acknowledgement at every user-turn release.

    Placed directly before the main LLM. The ``LLMContextFrame`` is forwarded
    before the router is consulted, so the main LLM is never delayed.
    """

    def __init__(
        self,
        *,
        decide: DecideFn,
        gate: AckGate,
        history_messages: int = 6,
        **kwargs,
    ):
        """Initialize the router.

        Args:
            decide: Coroutine that maps a conversation transcript to a decision.
            gate: The AckGate placed before TTS in the same pipeline.
            history_messages: How many recent spoken messages the router sees.
            **kwargs: Additional arguments passed to FrameProcessor.
        """
        super().__init__(**kwargs)
        self._decide = decide
        self._gate = gate
        self._history = history_messages
        self._task: asyncio.Task | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Forward frames; start a router call when a user turn is released."""
        await super().process_frame(frame, direction)

        if isinstance(frame, (InterruptionFrame, EndFrame, CancelFrame)):
            await self._cancel_pending()

        if (
            isinstance(frame, LLMContextFrame)
            and direction == FrameDirection.DOWNSTREAM
        ):
            messages = list(frame.context.messages)
            last = messages[-1] if messages else None
            if isinstance(last, dict) and last.get("role") == "user":
                await self._cancel_pending()
                turn = self._gate.begin_turn()
                await self.push_frame(frame, direction)
                self._task = self.create_task(
                    self._route(turn, messages), name="fast_router"
                )
                return

        await self.push_frame(frame, direction)

    async def cleanup(self):
        """Cancel any in-flight router call."""
        await self._cancel_pending()
        await super().cleanup()

    async def _cancel_pending(self):
        if self._task:
            task, self._task = self._task, None
            await self.cancel_task(task)

    async def _route(self, turn: int, messages: list):
        started = time.monotonic()
        try:
            decision = await self._decide(
                transcript_from_messages(messages, self._history)
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — a failed router must never affect the call
            logger.info(
                f"{self}: no decision ({type(e).__name__}) after "
                f"{(time.monotonic() - started) * 1000:.0f} ms"
            )
            return
        elapsed = (time.monotonic() - started) * 1000
        if decision is None:
            logger.info(f"{self}: no decision after {elapsed:.0f} ms")
            return
        ack = safe_ack(decision)
        outcome = await self._gate.offer(turn, ack) if ack else "no-ack"
        logger.info(
            f"{self}: route={decision.route} ack={decision.ack!r} {elapsed:.0f} ms -> {outcome}"
        )


def vertex_router_decider(
    *, project_id: str, location: str, model: str, prompt: str, timeout_secs: float
) -> DecideFn:
    """Build a DecideFn backed by a Vertex Gemini model in JSON mode."""
    from google import genai
    from google.genai import types

    client = genai.Client(vertexai=True, project=project_id, location=location)
    config = types.GenerateContentConfig(
        system_instruction=prompt,
        temperature=0.0,
        max_output_tokens=80,
        response_mime_type="application/json",
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )

    async def decide(transcript: str) -> RouterDecision | None:
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=model, contents=transcript, config=config
            ),
            timeout_secs,
        )
        data = json.loads(response.text or "{}")
        if not isinstance(data, dict):
            return None
        return RouterDecision(
            route=str(data.get("route", "")), ack=str(data.get("ack", ""))
        )

    return decide


def create_fast_router(
    config: dict, *, project_id: str | None
) -> tuple[FastRouterProcessor | None, AckGate | None]:
    """Build the router and its gate from a workflow's ``fast_router`` configuration."""
    if not project_id:
        logger.warning(
            "fast_router is enabled but no Vertex project_id is available; skipping"
        )
        return None, None
    gate = AckGate()
    decide = vertex_router_decider(
        project_id=project_id,
        location=config.get("location") or "europe-west1",
        model=config.get("model") or "gemini-2.5-flash",
        prompt=config.get("prompt") or DEFAULT_ROUTER_PROMPT,
        timeout_secs=float(config.get("timeout_ms") or 1200) / 1000,
    )
    router = FastRouterProcessor(
        decide=decide,
        gate=gate,
        history_messages=int(config.get("history_messages") or 6),
    )
    return router, gate
