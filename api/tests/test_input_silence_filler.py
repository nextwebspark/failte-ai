from types import SimpleNamespace

import pytest
from pipecat.frames.frames import InputAudioRawFrame
from pipecat.processors.filters.identity_filter import IdentityFilter
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.tests.utils import SleepFrame, run_test

from api.services.pipecat.input_silence_filler import InputSilenceFiller
from api.services.pipecat.pipeline_builder import build_realtime_pipeline

SAMPLE_RATE = 8000
FRAME_BYTES = 320  # 20 ms of 16-bit mono at 8 kHz


def _speech() -> InputAudioRawFrame:
    return InputAudioRawFrame(
        audio=b"\x01\x00" * (FRAME_BYTES // 2), sample_rate=SAMPLE_RATE, num_channels=1
    )


def _audio(frames):
    return [f for f in frames if isinstance(f, InputAudioRawFrame)]


def _silent(frame: InputAudioRawFrame) -> bool:
    return not any(frame.audio)


@pytest.mark.asyncio
async def test_fills_a_gap_with_real_time_silence():
    down, _ = await run_test(
        InputSilenceFiller(),
        frames_to_send=[_speech(), SleepFrame(sleep=0.5), _speech()],
    )

    frames = _audio(down)
    silent = [f for f in frames if _silent(f)]

    assert not _silent(frames[0]) and not _silent(frames[-1])
    # A 0.5 s gap is 25 frames of 20 ms; allow for scheduler slack.
    assert 18 <= len(silent) <= 28
    assert all(
        f.sample_rate == SAMPLE_RATE
        and f.num_channels == 1
        and len(f.audio) == FRAME_BYTES
        for f in silent
    )


@pytest.mark.asyncio
async def test_does_not_fill_while_audio_is_flowing():
    frames_to_send = []
    for _ in range(15):
        frames_to_send += [_speech(), SleepFrame(sleep=0.02)]

    down, _ = await run_test(InputSilenceFiller(), frames_to_send=frames_to_send)

    assert not any(_silent(f) for f in _audio(down))


@pytest.mark.asyncio
async def test_does_not_fill_before_the_first_audio_frame():
    down, _ = await run_test(
        InputSilenceFiller(), frames_to_send=[SleepFrame(sleep=0.3)]
    )

    assert _audio(down) == []


@pytest.mark.asyncio
async def test_stops_filling_when_audio_resumes():
    filler = InputSilenceFiller()
    frames_to_send = [_speech(), SleepFrame(sleep=0.3)]
    for _ in range(10):
        frames_to_send += [_speech(), SleepFrame(sleep=0.02)]

    down, _ = await run_test(filler, frames_to_send=frames_to_send)

    frames = _audio(down)
    first_resumed = next(i for i, f in enumerate(frames) if i > 0 and not _silent(f))
    assert any(_silent(f) for f in frames[:first_resumed])
    assert not any(_silent(f) for f in frames[first_resumed:])


class _AudioRecorder(FrameProcessor):
    """Stands in for the realtime service and keeps the audio it receives."""

    def __init__(self):
        super().__init__()
        self.audio = []

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            self.audio.append(frame)
        await self.push_frame(frame, direction)


def _realtime_pipeline(realtime_llm, input_silence_filler):
    # Pass-through stand-ins, so frames reach the realtime service when run.
    input_processor = IdentityFilter()
    output_processor = IdentityFilter()
    transport = SimpleNamespace(
        input=lambda: input_processor, output=lambda: output_processor
    )
    funnel = IdentityFilter()
    user_aggregator = IdentityFilter()
    pipeline = build_realtime_pipeline(
        transport,
        realtime_llm,
        IdentityFilter(),
        user_aggregator,
        IdentityFilter(),
        IdentityFilter(),
        IdentityFilter(),
        IdentityFilter(),
        funnel,
        input_silence_filler=input_silence_filler,
    )
    return pipeline, funnel, user_aggregator


def test_realtime_pipeline_places_the_filler_after_the_funnel():
    filler = InputSilenceFiller()
    realtime_llm = FrameProcessor()
    pipeline, funnel, user_aggregator = _realtime_pipeline(realtime_llm, filler)

    processors = pipeline.processors
    assert processors.index(filler) == processors.index(funnel) + 1
    assert processors.index(filler) < processors.index(user_aggregator)
    assert processors.index(filler) < processors.index(realtime_llm)


def test_realtime_pipeline_leaves_no_slot_without_a_filler():
    pipeline, _, _ = _realtime_pipeline(FrameProcessor(), None)

    assert None not in pipeline.processors
    assert not any(isinstance(p, InputSilenceFiller) for p in pipeline.processors)


@pytest.mark.asyncio
async def test_realtime_service_receives_silence_when_the_line_goes_quiet():
    # The realtime service's server-side VAD can only close the caller's turn
    # if it receives the silence after their last word.
    realtime_llm = _AudioRecorder()
    pipeline, _, _ = _realtime_pipeline(realtime_llm, InputSilenceFiller())

    await run_test(pipeline, frames_to_send=[_speech(), SleepFrame(sleep=0.5)])

    silent = [f for f in realtime_llm.audio if _silent(f)]
    assert not _silent(realtime_llm.audio[0])
    # 0.5 s with no audio from the line is ~20 frames once the 0.1 s gap
    # threshold has passed; allow for scheduler slack.
    assert len(silent) >= 15
