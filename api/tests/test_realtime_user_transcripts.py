"""A speech-to-speech model's late caller transcriptions are kept
(api/services/pipecat/realtime/user_transcripts.py): a Gemini Live call
lost the caller's name, number and party size from its transcript because
they arrived while the caller was muted."""

import pytest
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMUserAggregator,
    LLMUserAggregatorParams,
)
from pipecat.tests.utils import SleepFrame
from pipecat.turns.user_mute.always_user_mute_strategy import AlwaysUserMuteStrategy

from api.services.pipecat.realtime.user_transcripts import (
    keep_realtime_user_transcripts,
)
from pipecat.tests import run_test


def _muted_realtime_aggregator(context: LLMContext) -> LLMUserAggregator:
    return LLMUserAggregator(
        context,
        params=LLMUserAggregatorParams(user_mute_strategies=[AlwaysUserMuteStrategy()]),
        _realtime_service_mode=True,
    )


async def _said(aggregator: LLMUserAggregator, frames) -> list[str]:
    written: list[str] = []

    @aggregator.event_handler("on_user_turn_message_added")
    async def _added(_aggregator, message):
        written.append(message.content)

    await run_test(
        Pipeline([aggregator]), frames_to_send=frames, expected_down_frames=None
    )
    return written


FRAMES = [
    # The agent is speaking, so the caller is muted...
    BotStartedSpeakingFrame(),
    SleepFrame(),
    # ...when the model reports what the caller said a moment ago.
    InterimTranscriptionFrame(text="My name", user_id="", timestamp="t"),
    TranscriptionFrame(
        text="My name is Naveen, a table for three.", user_id="", timestamp="t"
    ),
    SleepFrame(),
]


@pytest.mark.asyncio
async def test_without_the_fix_a_muted_callers_line_is_lost():
    context = LLMContext()
    assert await _said(_muted_realtime_aggregator(context), FRAMES) == []


@pytest.mark.asyncio
async def test_a_muted_callers_finished_line_is_kept():
    context = LLMContext()
    aggregator = _muted_realtime_aggregator(context)
    keep_realtime_user_transcripts(aggregator)
    assert await _said(aggregator, FRAMES) == ["My name is Naveen, a table for three."]
    assert context.get_messages()[-1] == {
        "role": "user",
        "content": "My name is Naveen, a table for three.",
    }
