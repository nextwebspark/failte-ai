"""Keep every caller line a speech-to-speech model reports.

A realtime model (Gemini Live, Nova Sonic, ...) hears the caller's audio
itself and reports what was said as text afterwards, often while the agent is
already answering or running a tool. Two things in pipecat's user aggregator
then drop those lines, so the caller's name, number or party size go missing
from the transcript, the call's record and what is read from it after the
call, even though the model heard them and acted on them:

1. The user mute (while a tool runs, during speech that may not be
   interrupted, before the greeting ends) also throws away TranscriptionFrame.
   Muting is meant to stop new input; the audio is already muted upstream, so
   a transcription arriving then is of speech the model already took in.
2. A tool call starting during the caller's turn moves what they said into a
   stash that, in realtime mode, is never written.

In realtime mode a TranscriptionFrame doesn't start a turn or interrupt (the
service's own proposals do that), so letting it through only records it.
Interim transcriptions stay muted. Cascade calls (separate speech-to-text)
are not touched.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from pipecat.frames.frames import Frame, FunctionCallsStartedFrame, TranscriptionFrame


def keep_realtime_user_transcripts(user_aggregator: Any) -> None:
    """Apply both fixes to this call's user aggregator (an
    ``LLMUserAggregator`` in realtime service mode)."""
    original_mute = user_aggregator._maybe_mute_frame
    original_function_calls = user_aggregator._handle_function_calls_started

    async def maybe_mute_frame(frame: Frame) -> bool:
        # The original still runs: it keeps the mute state up to date.
        muted = await original_mute(frame)
        if muted and isinstance(frame, TranscriptionFrame):
            logger.debug("Realtime caller transcription kept while the user is muted")
            return False
        return muted

    async def handle_function_calls_started(frame: FunctionCallsStartedFrame) -> None:
        if (
            user_aggregator._realtime_service_mode
            and user_aggregator.aggregation_string()
        ):
            # Write what the caller has said so far now, as its own message,
            # rather than into the stash realtime mode never writes. No
            # inference: the model is already answering with the tool call.
            await user_aggregator._push_aggregation(run_llm=False)
        await original_function_calls(frame)

    user_aggregator._maybe_mute_frame = maybe_mute_frame
    user_aggregator._handle_function_calls_started = handle_function_calls_started
