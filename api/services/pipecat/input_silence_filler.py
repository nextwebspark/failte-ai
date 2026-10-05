"""Keep inbound audio continuous when the caller's line goes quiet.

Some phone legs stop sending audio while the caller is silent (discontinuous
transmission). Downstream that is indistinguishable from a caller who is still
talking: VAD cannot see the silence that ends a sentence, Google STT cannot
finalise it, so the user's turn is held open for seconds, and after ~10 s with
no audio Google closes the stream. ``InputSilenceFiller`` sits directly after
the transport input and, whenever no input audio has arrived for
``gap_threshold_secs``, pushes frames of digital silence at real-time pace
until real audio resumes.
"""

import asyncio
import time

from loguru import logger

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    StartFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# Cap on frames pushed in one tick, so a stalled event loop cannot release a
# large burst of silence at once.
_MAX_FRAMES_PER_TICK = 25


class InputSilenceFiller(FrameProcessor):
    """Fills gaps in inbound audio with real-time silence frames.

    Nothing is filled before the first real audio frame arrives. The silence
    frames copy the sample rate and channel count of the last real frame.
    """

    def __init__(
        self,
        *,
        gap_threshold_secs: float = 0.1,
        frame_secs: float = 0.02,
        **kwargs,
    ):
        """Initialize the filler.

        Args:
            gap_threshold_secs: How long inbound audio may be absent before
                silence is filled in. Kept above normal network jitter so a
                late packet is not doubled by fill.
            frame_secs: Duration of each silence frame.
            **kwargs: Additional arguments passed to FrameProcessor.
        """
        super().__init__(**kwargs)
        self._gap_threshold = gap_threshold_secs
        self._frame_secs = frame_secs
        self._sample_rate: int | None = None
        self._num_channels: int | None = None
        self._last_real: float | None = None
        self._covered_until: float | None = None
        self._filling = False
        self._fill_task: asyncio.Task | None = None
        self._started_at: float | None = None
        self._filled_frames = 0
        self._gaps = 0

    @property
    def filled_seconds(self) -> float:
        """Total seconds of silence filled in so far."""
        return self._filled_frames * self._frame_secs

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Track inbound audio and pass every frame through unchanged."""
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            self._started_at = time.monotonic()
            if not self._fill_task:
                self._fill_task = self.create_task(
                    self._fill_loop(), name="input_silence_fill"
                )
            return

        if isinstance(frame, (EndFrame, CancelFrame)):
            await self._stop()
            await self.push_frame(frame, direction)
            return

        if (
            isinstance(frame, InputAudioRawFrame)
            and direction == FrameDirection.DOWNSTREAM
        ):
            now = time.monotonic()
            self._sample_rate = frame.sample_rate
            self._num_channels = frame.num_channels
            self._last_real = now
            self._covered_until = now
            self._filling = False

        await self.push_frame(frame, direction)

    async def cleanup(self):
        """Stop the fill task."""
        await self._stop()
        await super().cleanup()

    async def _stop(self):
        if self._fill_task:
            task, self._fill_task = self._fill_task, None
            await self.cancel_task(task)
            if self._started_at is not None:
                total = time.monotonic() - self._started_at
                logger.info(
                    f"{self}: filled {self.filled_seconds:.1f}s of silence in "
                    f"{self._gaps} gaps over {total:.1f}s "
                    f"({self.filled_seconds / total * 100 if total else 0:.0f}%)"
                )

    async def _fill_loop(self):
        while True:
            await asyncio.sleep(self._frame_secs)
            if self._last_real is None:
                continue
            now = time.monotonic()
            if now - self._last_real < self._gap_threshold:
                continue
            if not self._filling:
                self._filling = True
                self._gaps += 1
            silence = bytes(
                int(self._sample_rate * self._frame_secs) * self._num_channels * 2
            )
            pushed = 0
            # Cover the time elapsed since the last real frame, so downstream
            # sees silence of the true duration rather than a truncated one.
            while (
                self._covered_until + self._frame_secs <= now
                and pushed < _MAX_FRAMES_PER_TICK
            ):
                await self.push_frame(
                    InputAudioRawFrame(
                        audio=silence,
                        sample_rate=self._sample_rate,
                        num_channels=self._num_channels,
                    )
                )
                self._covered_until += self._frame_secs
                self._filled_frames += 1
                pushed += 1
            if pushed == _MAX_FRAMES_PER_TICK:
                # Drop a backlog left by a stalled loop instead of replaying it.
                self._covered_until = max(self._covered_until, now - self._frame_secs)
