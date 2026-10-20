"""The AI and recording disclosure through the full ``_run_pipeline`` call path.

An agent whose stored configuration predates the setting (no
``call_disclosure`` key) still discloses: the notice is spoken through the
real TTS and output transport ahead of the start node's greeting, lands in the
assistant context once, and the conversation then carries on normally.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from pipecat.frames.frames import TranscriptionFrame
from pipecat.tests.mock_transport import MockTransport
from pipecat.transports.base_transport import TransportParams
from pipecat.utils.time import time_now_iso8601

from api.enums import WorkflowRunMode, WorkflowRunState
from api.schemas.workflow_configurations import DEFAULT_CALL_DISCLOSURE_TEXT
from api.services.pipecat.audio_config import create_audio_config
from api.services.pipecat.run_pipeline import _run_pipeline
from api.services.pipecat.worker_runner import wait_for_pipeline_worker_started
from api.services.workflow.pipecat_engine import PipecatEngine
from api.tests.integrations._run_pipeline_helpers import (
    create_workflow_run_rows,
    patch_run_pipeline_externals,
)
from api.tests.integrations.test_run_pipeline_text_greeting import (
    GREETING_TEXT,
    WORKFLOW_DEFINITION,
    _find_processor_by_class_name,
    _wait_for,
)
from pipecat.tests import MockLLMService, MockTTSService

TEST_HARD_TIMEOUT_SECONDS = 25.0


@pytest.fixture
async def workflow_run_setup(db_session, async_session):
    return await create_workflow_run_rows(
        db_session,
        async_session,
        workflow_definition=WORKFLOW_DEFINITION,
        name_prefix="Call Disclosure Integration",
        provider_id_suffix="call-disclosure",
    )


def _assistant_texts(context) -> list[str]:
    return [
        str(message.get("content") or "")
        for message in context.get_messages()
        if isinstance(message, dict) and message.get("role") == "assistant"
    ]


async def _run_test_body(workflow_run_setup, db_session) -> None:
    # The rows carry no workflow configurations at all, like an agent saved
    # before the disclosure setting existed.
    workflow_run, user, workflow = workflow_run_setup

    llm = MockLLMService(
        mock_steps=[
            MockLLMService.create_function_call_chunks(
                function_name="end_call", arguments={}, tool_call_id="call_end_1"
            )
        ],
        chunk_delay=0.001,
    )
    tts = MockTTSService(mock_audio_duration_ms=50, frame_delay=0)
    transport = MockTransport(
        TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_out_end_silence_secs=0,
        )
    )
    captured_task: list = []
    captured_engine: list[PipecatEngine] = []

    def create_engine(*args, **kwargs):
        engine = PipecatEngine(*args, **kwargs)
        captured_engine.append(engine)
        return engine

    pipeline_task = None
    try:
        with (
            patch_run_pipeline_externals(captured_task, llm=llm, tts=tts),
            patch(
                "api.services.pipecat.run_pipeline.get_ws_sender",
                return_value=AsyncMock(),
            ),
            patch(
                "api.services.pipecat.run_pipeline.PipecatEngine",
                side_effect=create_engine,
            ),
        ):
            run_task = asyncio.create_task(
                _run_pipeline(
                    transport=transport,
                    workflow_id=workflow.id,
                    workflow_run_id=workflow_run.id,
                    user_id=user.id,
                    audio_config=create_audio_config(WorkflowRunMode.SMALLWEBRTC.value),
                    user_provider_id=user.provider_id,
                )
            )
            for _ in range(60):
                if captured_task or run_task.done():
                    break
                await asyncio.sleep(0.05)
            if run_task.done() and not captured_task:
                run_task.result()
            pipeline_task = captured_task[0]
            await wait_for_pipeline_worker_started(
                pipeline_task, timeout=3.0, run_task=run_task
            )

            context = _find_processor_by_class_name(
                pipeline_task, "LLMAssistantAggregator"
            ).context

            # Both lines reach the caller, the disclosure first.
            assert await _wait_for(
                lambda: any(GREETING_TEXT in t for t in _assistant_texts(context)),
                timeout=5.0,
            ), f"Messages: {context.get_messages()}"
            texts = _assistant_texts(context)
            disclosure_at = [
                i for i, t in enumerate(texts) if DEFAULT_CALL_DISCLOSURE_TEXT in t
            ]
            greeting_at = [i for i, t in enumerate(texts) if GREETING_TEXT in t]
            assert len(disclosure_at) == 1, texts
            assert disclosure_at[0] < greeting_at[0], texts
            assert captured_engine[0]._call_disclosure_done
            assert await _wait_for(
                lambda: not captured_engine[0].speech_playback.greeting_pending,
                timeout=2.0,
            )
            assert not captured_engine[0].speech_playback.mutes_user
            assert llm.get_current_step() == 0

            # The caller replies; the call proceeds and ends as usual.
            await pipeline_task.queue_frame(
                TranscriptionFrame(
                    text="I want to end the call now please.",
                    user_id="test-user",
                    timestamp=time_now_iso8601(),
                )
            )
            await asyncio.wait_for(run_task, timeout=10.0)

        refreshed = await db_session.get_workflow_run_by_id(workflow_run.id)
        assert refreshed.state == WorkflowRunState.COMPLETED.value
        assert [
            t for t in _assistant_texts(context) if DEFAULT_CALL_DISCLOSURE_TEXT in t
        ] == [DEFAULT_CALL_DISCLOSURE_TEXT]
    finally:
        if pipeline_task is not None and not pipeline_task.has_finished():
            try:
                await asyncio.wait_for(pipeline_task.cancel(), timeout=3.0)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_disclosure_is_spoken_before_the_greeting_on_a_live_call(
    workflow_run_setup, db_session
):
    await asyncio.wait_for(
        _run_test_body(workflow_run_setup, db_session),
        timeout=TEST_HARD_TIMEOUT_SECONDS,
    )
