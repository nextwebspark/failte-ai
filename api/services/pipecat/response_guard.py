"""Never answer a caller with silence.

A generation can come back with nothing to say: the model stream stalls and
times out, the response is withheld (safety, recitation, a malformed
response), or the model simply returns no text and no tool call. The LLM
service reports that as a non-fatal error, or not at all, and the turn ends
with the caller hearing nothing. On a phone call that is the worst outcome,
and worst of all after "I have crushing chest pain".

:class:`EmptyResponseGuard` sits directly after the LLM. When a generation
that answers the caller ends with no speakable text and no tool call, it asks
the LLM once more with the same context; if that also comes back empty, it
speaks a fixed line instead. The line sends anyone describing an emergency to
112/999, and otherwise asks the caller to say it again.

Only generations that answer the caller are retried: the context's last
message must be the caller's. A generation after a tool result may rightly
say nothing (the tool spoke), except in the call's closing step, which must
say goodbye: an empty one there gets a fixed short goodbye.

It also keeps a goodbye from leaving the line open: a reply whose last words
are a farewell ("... Have a lovely day!"), with no tool call and outside the
closing step, makes the engine end the call after it, the way the end-call
tool would.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    FunctionCallInProgressFrame,
    FunctionCallsFromLLMInfoFrame,
    FunctionCallsStartedFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# What the caller hears when the model gives nothing twice.
EMERGENCY_FALLBACK = "If this is an emergency, please hang up now and dial 112 or 999."
GAS_FALLBACK = (
    "If you can smell gas, leave the building now and, once you're outside, "
    "ring Gas Networks Ireland on 1, 8, 0, 0, 2, 0, 5, 0, 5, 0. If anyone is "
    "unwell or there's a fire, dial 112 or 999."
)
# The closing step's goodbye, when the model gives nothing there.
CLOSING_FALLBACK = "Thanks for calling. Goodbye."
GENERIC_FALLBACK = (
    "Sorry, I didn't catch that. Could you say it again? If this is an "
    "emergency, please hang up and dial 112 or 999."
)

_GAS_WORDS = re.compile(r"\bgas\b|carbon monoxide|fumes", re.IGNORECASE)
# Words that make the fixed line lead with 112/999. Over-inclusive on purpose:
# the cost of a false match is one sentence the caller didn't need.
_EMERGENCY_WORDS = re.compile(
    r"chest|heart|breath|bleed|blood|collaps|unconscious|faint|stroke|seiz|"
    r"choking|anaphyla|allerg|overdose|suicid|kill (my|him|her)self|"
    r"hurt (my|him|her)self|ambulance|emergency|accident|fire|smoke|"
    r"numb|paralys|can'?t (move|breathe)",
    re.IGNORECASE,
)
# A reply that ends the conversation: its last words are a farewell.
_FAREWELL = re.compile(
    r"\b(good ?bye|bye(\s+(now|for now))?|take care|all the best|"
    r"have a (lovely|good|great|nice|wonderful|safe) "
    r"(day|evening|night|weekend|afternoon|morning|one))"
    r"[\s.!]*$",
    re.IGNORECASE,
)
# A stall shorter than this was a fast empty answer (blocked, malformed, or
# just nothing) and is worth asking again. A slower one has already used the
# service's own timeout retry, so the caller has waited long enough.
_RETRY_WITHIN_SECS = 10.0

ContextProvider = Callable[[], Any]
Rerun = Callable[[Any], Awaitable[None]]


def _speakable(text: str) -> bool:
    return any(ch.isalnum() for ch in text)


def _message_role(message: Any) -> str | None:
    if isinstance(message, dict):
        role = message.get("role")
        return role if isinstance(role, str) else None
    role = getattr(message, "role", None)
    return role if isinstance(role, str) else None


def _message_text(message: Any) -> str:
    content = (
        message.get("content")
        if isinstance(message, dict)
        else getattr(message, "content", None)
    )
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    parts = getattr(message, "parts", None)
    if isinstance(parts, list):
        return " ".join(getattr(p, "text", "") or "" for p in parts)
    return ""


def _last_caller_message(context: Any) -> str | None:
    """The caller's words when the context ends on them, else None."""
    if context is None:
        return None
    try:
        messages = context.get_messages()
    except Exception:  # noqa: BLE001 - a guard must never break the call
        return None
    for message in reversed(messages or []):
        role = _message_role(message)
        if role is None:
            # Provider-specific entries (thought signatures) carry no role.
            continue
        return _message_text(message) if role == "user" else None
    return None


def is_farewell(text: str) -> bool:
    """Whether a reply's last words say goodbye ("... Have a lovely day!")."""
    return bool(_FAREWELL.search(text.strip()))


def fallback_line(caller_text: str | None) -> str:
    """The fixed line for a caller the model gave nothing: gas first, then
    any sign of an emergency, else a plain "say that again"."""
    if caller_text and _GAS_WORDS.search(caller_text):
        return GAS_FALLBACK
    if caller_text and _EMERGENCY_WORDS.search(caller_text):
        return EMERGENCY_FALLBACK
    return GENERIC_FALLBACK


class EmptyResponseGuard(FrameProcessor):
    """Retry an empty answer to the caller once, then speak a fixed line."""

    def __init__(
        self,
        *,
        context_provider: ContextProvider,
        rerun: Rerun,
        on_retry: Callable[[], None] | None = None,
        in_closing_step: Callable[[], bool] | None = None,
        on_farewell: Callable[[], None] | None = None,
        retry_within_secs: float = _RETRY_WITHIN_SECS,
    ):
        super().__init__()
        self._context_provider = context_provider
        self._rerun = rerun
        self._on_retry = on_retry
        self._in_closing_step = in_closing_step
        self._on_farewell = on_farewell
        self._text: list[str] = []
        self._tool_called = False
        self._closing_spoken = False
        self._retry_within_secs = retry_within_secs
        self._open = False
        self._started_at = 0.0
        self._acted = False
        self._interrupted = False
        # Set when the next generation is this guard's own retry.
        self._retrying = False

    def _said_goodbye_and_left_the_line_open(self) -> bool:
        """This reply was a farewell with no tool call, outside the closing
        step (which ends the call itself)."""
        if self._on_farewell is None or self._tool_called or self._interrupted:
            return False
        if not is_farewell("".join(self._text)):
            return False
        try:
            closing = bool(self._in_closing_step and self._in_closing_step())
        except Exception:  # noqa: BLE001 - a guard must never break the call
            return False
        return not closing

    def _closing_in_silence(self) -> bool:
        """The call's closing step produced nothing, for the first time."""
        if self._closing_spoken or self._in_closing_step is None:
            return False
        try:
            return bool(self._in_closing_step())
        except Exception:  # noqa: BLE001 - a guard must never break the call
            return False

    def _reset_response(self) -> None:
        self._open = True
        self._started_at = time.monotonic()
        self._acted = False
        self._interrupted = False
        self._text = []
        self._tool_called = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, (CancelFrame, EndFrame)):
            self._open = False
            self._retrying = False
        elif isinstance(frame, InterruptionFrame):
            self._interrupted = True
            self._retrying = False
        elif direction is FrameDirection.DOWNSTREAM:
            if isinstance(frame, LLMFullResponseStartFrame):
                self._reset_response()
            elif self._open and isinstance(frame, LLMTextFrame):
                self._text.append(frame.text or "")
                if _speakable(frame.text or ""):
                    self._acted = True
            elif isinstance(frame, TTSSpeakFrame) and _speakable(frame.text or ""):
                self._acted = True
        if isinstance(
            frame,
            (
                FunctionCallsFromLLMInfoFrame,
                FunctionCallsStartedFrame,
                FunctionCallInProgressFrame,
            ),
        ):
            self._acted = True
            self._tool_called = True

        is_end = (
            isinstance(frame, LLMFullResponseEndFrame)
            and direction is FrameDirection.DOWNSTREAM
            and self._open
        )
        if not is_end:
            await self.push_frame(frame, direction)
            return

        self._open = False
        was_retry, self._retrying = self._retrying, False
        if self._acted or self._interrupted:
            await self.push_frame(frame, direction)
            if self._said_goodbye_and_left_the_line_open():
                logger.warning(
                    f"{self}: the agent said goodbye without its end-call tool; "
                    "ending the call after that reply"
                )
                self._on_farewell()
            return
        context = self._context_provider()
        caller_text = _last_caller_message(context)
        if caller_text is None:
            await self.push_frame(frame, direction)
            if self._closing_in_silence():
                logger.warning(
                    f"{self}: the closing step said nothing; speaking the "
                    f"fixed goodbye: {CLOSING_FALLBACK!r}"
                )
                self._closing_spoken = True
                await self.push_frame(
                    TTSSpeakFrame(CLOSING_FALLBACK, append_to_context=True)
                )
            return

        elapsed = time.monotonic() - self._started_at
        if not was_retry and elapsed < self._retry_within_secs:
            logger.warning(
                f"{self}: the model gave the caller nothing after {elapsed:.1f}s; "
                "asking it once more"
            )
            # Counted before the end frame moves on, so a text chat turn
            # waits for the retry instead of settling on silence.
            if self._on_retry is not None:
                self._on_retry()
            self._retrying = True
            await self.push_frame(frame, direction)
            await self._rerun(context)
            return

        line = fallback_line(caller_text)
        logger.warning(
            f"{self}: the model gave the caller nothing "
            f"({'after a retry' if was_retry else f'after {elapsed:.1f}s'}); "
            f"speaking the fixed line: {line!r}"
        )
        # After the end frame, so it is spoken as its own utterance rather
        # than inside a response the TTS has already closed.
        await self.push_frame(frame, direction)
        await self.push_frame(TTSSpeakFrame(line, append_to_context=True))
