"""EmptyResponseGuard: an empty answer to the caller is asked for again once,
then replaced by a fixed line; never a silent turn (8 Nov 2026, CL-06)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pipecat.frames.frames import (
    FunctionCallFromLLM,
    FunctionCallsFromLLMInfoFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TTSSpeakFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection

from api.services.pipecat.response_guard import (
    CLOSING_FALLBACK,
    EMERGENCY_FALLBACK,
    GAS_FALLBACK,
    GENERIC_FALLBACK,
    EmptyResponseGuard,
    fallback_line,
)

DOWN = FrameDirection.DOWNSTREAM
CHEST = (
    "Hi, I've had a crushing pain in my chest for the last twenty minutes "
    "and my left arm feels numb."
)


def _context(*messages):
    context = LLMContext()
    context.set_messages(list(messages))
    return context


def _guard(context, **kwargs):
    rerun = AsyncMock()
    on_retry = MagicMock()
    guard = EmptyResponseGuard(
        context_provider=lambda: context, rerun=rerun, on_retry=on_retry, **kwargs
    )
    guard.push_frame = AsyncMock()
    return guard, rerun, on_retry


def _pushed(guard):
    return [call.args[0] for call in guard.push_frame.await_args_list]


async def _response(guard, *frames):
    await guard.process_frame(LLMFullResponseStartFrame(), DOWN)
    for frame in frames:
        await guard.process_frame(frame, DOWN)
    await guard.process_frame(LLMFullResponseEndFrame(), DOWN)


@pytest.mark.asyncio
async def test_a_spoken_answer_passes_untouched():
    context = _context({"role": "user", "content": CHEST})
    guard, rerun, on_retry = _guard(context)
    await _response(guard, LLMTextFrame("Please hang up now and dial 112 or 999."))
    rerun.assert_not_awaited()
    on_retry.assert_not_called()
    assert not any(isinstance(f, TTSSpeakFrame) for f in _pushed(guard))


@pytest.mark.asyncio
async def test_an_empty_answer_is_asked_for_again_once():
    context = _context({"role": "user", "content": CHEST})
    guard, rerun, on_retry = _guard(context)
    await _response(guard)
    rerun.assert_awaited_once_with(context)
    on_retry.assert_called_once()
    # The end frame still goes on, so the response is closed downstream.
    assert isinstance(_pushed(guard)[-1], LLMFullResponseEndFrame)


@pytest.mark.asyncio
async def test_a_second_empty_answer_speaks_the_fixed_line():
    context = _context({"role": "user", "content": CHEST})
    guard, rerun, _ = _guard(context)
    await _response(guard)
    await _response(guard, LLMTextFrame("  "))
    assert rerun.await_count == 1
    pushed = _pushed(guard)
    spoken = [f for f in pushed if isinstance(f, TTSSpeakFrame)]
    assert [f.text for f in spoken] == [EMERGENCY_FALLBACK]
    assert spoken[0].append_to_context is True
    # Spoken after the response it replaces has closed.
    assert pushed[-1] is spoken[0]
    assert isinstance(pushed[-2], LLMFullResponseEndFrame)


@pytest.mark.asyncio
async def test_a_slow_empty_answer_is_not_retried():
    context = _context({"role": "user", "content": "Do you open on Sunday?"})
    guard, rerun, _ = _guard(context, retry_within_secs=0.0)
    await _response(guard)
    rerun.assert_not_awaited()
    spoken = [f.text for f in _pushed(guard) if isinstance(f, TTSSpeakFrame)]
    assert spoken == [GENERIC_FALLBACK]


@pytest.mark.asyncio
async def test_a_tool_call_is_an_answer():
    context = _context({"role": "user", "content": "Wrong number, sorry."})
    guard, rerun, _ = _guard(context)
    call = FunctionCallFromLLM(
        function_name="end_call", tool_call_id="1", arguments={}, context=context
    )
    await _response(guard, FunctionCallsFromLLMInfoFrame(function_calls=[call]))
    rerun.assert_not_awaited()
    assert not any(isinstance(f, TTSSpeakFrame) for f in _pushed(guard))


@pytest.mark.asyncio
async def test_after_a_tool_result_silence_is_allowed():
    context = _context(
        {"role": "user", "content": "Bye."},
        {"role": "assistant", "content": "", "tool_calls": []},
        {"role": "tool", "content": "ok", "tool_call_id": "1"},
    )
    guard, rerun, _ = _guard(context)
    await _response(guard)
    rerun.assert_not_awaited()
    assert not any(isinstance(f, TTSSpeakFrame) for f in _pushed(guard))


@pytest.mark.asyncio
async def test_a_silent_closing_step_says_a_fixed_goodbye_once():
    context = _context(
        {"role": "user", "content": "OK, thanks."},
        {"role": "assistant", "content": "", "tool_calls": []},
        {"role": "tool", "content": "ok", "tool_call_id": "1"},
    )
    guard, rerun, _ = _guard(context, in_closing_step=lambda: True)
    await _response(guard)
    await _response(guard)
    rerun.assert_not_awaited()
    spoken = [f.text for f in _pushed(guard) if isinstance(f, TTSSpeakFrame)]
    assert spoken == [CLOSING_FALLBACK]


@pytest.mark.asyncio
async def test_a_spoken_goodbye_needs_no_fixed_one():
    context = _context(
        {"role": "user", "content": "OK, thanks."},
        {"role": "tool", "content": "ok", "tool_call_id": "1"},
    )
    guard, _, _ = _guard(context, in_closing_step=lambda: True)
    await _response(guard, LLMTextFrame("Thanks for calling, goodbye."))
    assert not any(isinstance(f, TTSSpeakFrame) for f in _pushed(guard))


@pytest.mark.asyncio
async def test_an_interrupted_response_is_left_alone():
    context = _context({"role": "user", "content": CHEST})
    guard, rerun, _ = _guard(context)
    await guard.process_frame(LLMFullResponseStartFrame(), DOWN)
    await guard.process_frame(InterruptionFrame(), DOWN)
    await guard.process_frame(LLMFullResponseEndFrame(), DOWN)
    rerun.assert_not_awaited()


def test_fallback_line_by_what_the_caller_said():
    assert fallback_line(CHEST) == EMERGENCY_FALLBACK
    assert fallback_line("I can smell gas in the kitchen") == GAS_FALLBACK
    assert fallback_line("My husband collapsed") == EMERGENCY_FALLBACK
    assert fallback_line("Can I book a table for two?") == GENERIC_FALLBACK
    assert fallback_line("Las Vegas trip") == GENERIC_FALLBACK
    assert "1, 8, 0, 0, 2, 0, 5, 0, 5, 0" in GAS_FALLBACK
