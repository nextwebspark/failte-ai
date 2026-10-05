import asyncio

import pytest
from pipecat.frames.frames import LLMContextFrame, LLMTextFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.tests.utils import SleepFrame, run_test

from api.services.pipecat.fast_router import (
    AckGate,
    FastRouterProcessor,
    RouterDecision,
    safe_ack,
    transcript_from_messages,
)


def _context(*turns):
    return LLMContext(messages=[{"role": r, "content": c} for r, c in turns])


def _decider(decision, delay=0.05, calls=None):
    async def decide(transcript):
        if calls is not None:
            calls.append(transcript)
        await asyncio.sleep(delay)
        return decision

    return decide


def _pipeline(decide):
    gate = AckGate()
    return Pipeline([FastRouterProcessor(decide=decide, gate=gate), gate])


def _acks(frames):
    return [f.text for f in frames if isinstance(f, TTSSpeakFrame)]


@pytest.mark.asyncio
async def test_ack_is_spoken_after_forwarding_the_context():
    ctx = _context(
        ("assistant", "How can I help?"), ("user", "Do you have life jackets?")
    )
    down, _ = await run_test(
        _pipeline(_decider(RouterDecision("product_search", "Sure, let me look."))),
        frames_to_send=[LLMContextFrame(context=ctx), SleepFrame(sleep=0.2)],
    )

    kinds = [type(f) for f in down if isinstance(f, (LLMContextFrame, TTSSpeakFrame))]
    assert kinds == [LLMContextFrame, TTSSpeakFrame]
    assert _acks(down) == ["Sure, let me look."]


@pytest.mark.asyncio
async def test_ack_is_dropped_when_the_main_llm_speaks_first():
    ctx = _context(("user", "Do you have life jackets?"))
    down, _ = await run_test(
        _pipeline(
            _decider(RouterDecision("product_search", "Sure, let me look."), delay=0.2)
        ),
        frames_to_send=[
            LLMContextFrame(context=ctx),
            LLMTextFrame("We have two lifejackets."),
            SleepFrame(sleep=0.4),
        ],
    )

    assert _acks(down) == []


@pytest.mark.asyncio
async def test_no_router_call_when_the_last_message_is_not_the_caller():
    calls = []
    ctx = _context(("user", "Hi"), ("assistant", "Hello, how can I help?"))
    down, _ = await run_test(
        _pipeline(_decider(RouterDecision("other", "Sure."), calls=calls)),
        frames_to_send=[LLMContextFrame(context=ctx), SleepFrame(sleep=0.15)],
    )

    assert calls == []
    assert _acks(down) == []


@pytest.mark.asyncio
async def test_a_failing_router_does_not_affect_the_turn():
    async def broken(transcript):
        raise TimeoutError

    ctx = _context(("user", "Do you have life jackets?"))
    down, _ = await run_test(
        _pipeline(broken),
        frames_to_send=[LLMContextFrame(context=ctx), SleepFrame(sleep=0.1)],
    )

    assert any(isinstance(f, LLMContextFrame) for f in down)
    assert _acks(down) == []


@pytest.mark.asyncio
async def test_tool_filler_is_dropped_after_the_router_acknowledged():
    ctx = _context(("user", "Do you have life jackets?"))
    down, _ = await run_test(
        _pipeline(_decider(RouterDecision("product_search", "Sure, let me look."))),
        frames_to_send=[
            LLMContextFrame(context=ctx),
            SleepFrame(sleep=0.15),
            TTSSpeakFrame("Let me have a look for you.", append_to_context=False),
            LLMTextFrame("We have two lifejackets."),
            TTSSpeakFrame("Later filler.", append_to_context=False),
        ],
    )

    assert _acks(down) == ["Sure, let me look.", "Later filler."]


@pytest.mark.asyncio
async def test_tool_filler_plays_when_the_router_stayed_silent():
    ctx = _context(("user", "Yes, that's correct."))
    down, _ = await run_test(
        _pipeline(_decider(RouterDecision("confirm_or_correct", ""))),
        frames_to_send=[
            LLMContextFrame(context=ctx),
            SleepFrame(sleep=0.15),
            TTSSpeakFrame(
                "Just a moment, I'm booking that in.", append_to_context=False
            ),
        ],
    )

    assert _acks(down) == ["Just a moment, I'm booking that in."]


@pytest.mark.parametrize(
    "decision, expected",
    [
        (RouterDecision("product_search", "Sure, one moment."), "Sure, one moment."),
        (RouterDecision("end_call", "Goodbye now."), ""),
        (RouterDecision("product_detail", "It's 63 euro."), ""),
        (RouterDecision("store_info", "Open until 5:30."), ""),
        (RouterDecision("other", ""), ""),
        (RouterDecision("other", "one two three four five six seven eight nine"), ""),
    ],
)
def test_safe_ack(decision, expected):
    assert safe_ack(decision) == expected


def test_transcript_keeps_only_recent_spoken_messages():
    messages = [
        {"role": "system", "content": "prompt"},
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": [{"type": "text", "text": "Life jackets?"}]},
        {"role": "tool", "content": "{}"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "The Baltic one."},
    ]

    assert (
        transcript_from_messages(messages, 2)
        == "Caller: Life jackets?\nCaller: The Baltic one."
    )
