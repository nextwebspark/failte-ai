import pytest
from pipecat.frames.frames import InputAudioRawFrame
from pipecat.tests.utils import SleepFrame, run_test

from api.services.pipecat.input_silence_filler import InputSilenceFiller

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
