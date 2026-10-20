"""The AI and recording disclosure played at the start of every call.

EU AI Act Art. 50 requires telling callers they are talking to an AI, and Irish
law requires notice that the call is recorded. The disclosure is queued from
``queue_node_opening`` so every entry point shares it; these tests drive that
method directly with the speech primitives replaced by recorders.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from pydantic import ValidationError

from api.enums import AnswerAction
from api.schemas.answer_supervisor import AnswerMessage, AnswerSupervisorConfig
from api.schemas.workflow_configurations import (
    DEFAULT_CALL_DISCLOSURE_TEXT,
    MAX_CALL_DISCLOSURE_TEXT_LENGTH,
    CallDisclosureConfiguration,
    WorkflowConfigurationDefaults,
    resolve_call_disclosure,
)
from api.services.pipecat.answer_classification import MachineSubtype
from api.services.pipecat.processors.answer_supervisor import AnswerVerdict
from api.services.pipecat.speech_playback import PlaybackOutcome
from api.services.workflow.answer_handling import handle_answer
from api.services.workflow.dto import (
    EdgeDataDTO,
    EndCallNodeData,
    Position,
    ReactFlowDTO,
    RFEdgeDTO,
    RFNodeDTO,
    StartCallNodeData,
)
from api.services.workflow.pipecat_engine import PipecatEngine
from api.services.workflow.workflow_graph import WorkflowGraph

GREETING = "Hi {{customer_name}}, this is Sarah."
DISCLOSURE = "Hi {{customer_name}}, this call is with an AI and may be recorded."
RENDERED_DISCLOSURE = "Hi Ada, this call is with an AI and may be recorded."


# ─── Schema ─────────────────────────────────────────────────────


def test_disclosure_is_on_by_default():
    config = WorkflowConfigurationDefaults()

    assert config.call_disclosure.enabled is True
    assert config.call_disclosure.type == "text"
    assert config.call_disclosure.text == DEFAULT_CALL_DISCLOSURE_TEXT
    assert config.call_disclosure.recording_id is None


@pytest.mark.parametrize("stored", [{}, {"call_disclosure": None}])
def test_agents_saved_before_the_setting_existed_disclose(stored):
    config = WorkflowConfigurationDefaults.model_validate(stored)

    assert config.call_disclosure.enabled is True
    assert resolve_call_disclosure(stored).enabled is True
    assert resolve_call_disclosure(None).enabled is True


def test_partial_disclosure_keeps_defaults_for_missing_fields():
    config = WorkflowConfigurationDefaults.model_validate(
        {"call_disclosure": {"enabled": False, "text": None}}
    )

    assert config.call_disclosure.enabled is False
    assert config.call_disclosure.text == DEFAULT_CALL_DISCLOSURE_TEXT


def test_disclosure_text_is_bounded():
    CallDisclosureConfiguration(text="a" * MAX_CALL_DISCLOSURE_TEXT_LENGTH)
    with pytest.raises(ValidationError):
        CallDisclosureConfiguration(text="a" * (MAX_CALL_DISCLOSURE_TEXT_LENGTH + 1))


def test_disclosure_type_is_text_or_audio():
    with pytest.raises(ValidationError):
        CallDisclosureConfiguration(type="video")


def test_enabled_disclosure_needs_something_to_say():
    with pytest.raises(ValidationError):
        CallDisclosureConfiguration(text="   ")
    # A recording alone is enough; a disabled disclosure needs nothing.
    CallDisclosureConfiguration(type="audio", text="", recording_id="disclosure_1")
    CallDisclosureConfiguration(enabled=False, text="")


def test_blank_recording_id_is_unset():
    assert CallDisclosureConfiguration(recording_id="  ").recording_id is None


def test_invalid_stored_disclosure_falls_back_to_the_default_notice():
    resolved = resolve_call_disclosure({"call_disclosure": {"type": "video"}})

    assert resolved == CallDisclosureConfiguration()


# ─── Engine ─────────────────────────────────────────────────────


def _workflow(*, greeting: str | None = GREETING, greeting_type: str = "text"):
    return WorkflowGraph(
        ReactFlowDTO(
            nodes=[
                RFNodeDTO(
                    id="start",
                    type="startCall",
                    position=Position(x=0, y=0),
                    data=StartCallNodeData(
                        name="Start",
                        prompt="Prompt",
                        is_start=True,
                        add_global_prompt=False,
                        greeting=greeting if greeting_type == "text" else None,
                        greeting_type=greeting_type,
                        greeting_recording_id=(
                            "7" if greeting_type == "audio" else None
                        ),
                        extraction_enabled=False,
                    ),
                ),
                RFNodeDTO(
                    id="end",
                    type="endCall",
                    position=Position(x=0, y=200),
                    data=EndCallNodeData(
                        name="End",
                        prompt="End",
                        is_end=True,
                        add_global_prompt=False,
                        extraction_enabled=False,
                    ),
                ),
            ],
            edges=[
                RFEdgeDTO(
                    id="e",
                    source="start",
                    target="end",
                    data=EdgeDataDTO(label="End", condition="End"),
                )
            ],
        )
    )


def _engine(
    disclosure: CallDisclosureConfiguration | None,
    *,
    is_realtime: bool = False,
    failing_recordings: frozenset = frozenset(),
    **workflow_kwargs,
):
    """An engine whose speech primitives record what the opening queued."""
    engine = PipecatEngine(
        workflow=_workflow(**workflow_kwargs),
        call_context_vars={"customer_name": "Ada"},
        workflow_run_id=1,
        is_realtime=is_realtime,
        call_disclosure=disclosure,
    )
    calls: list[tuple] = []
    engine._active_agent.worker = SimpleNamespace(queue_frame=AsyncMock())
    engine._active_agent.llm = MagicMock()
    engine._fetch_recording_audio = AsyncMock()
    engine._transport_output = SimpleNamespace(queue_frame=AsyncMock())

    async def queue_speech(text=None, **kwargs):
        source = next(
            (kwargs[key] for key in ("recording_id", "recording_pk") if key in kwargs),
            text,
        )
        failed = source in failing_recordings
        calls.append(("queue_speech", source, kwargs))
        speech = engine.speech_playback.create(greeting=kwargs.get("greeting", False))
        speech.finish(PlaybackOutcome.FAILED if failed else PlaybackOutcome.PLAYED)
        return speech

    async def speak(text, **kwargs):
        calls.append(("speak", text, kwargs))
        engine.speech_playback._expected_response.finish(PlaybackOutcome.PLAYED)

    async def run_llm(_context):
        calls.append(("run_llm",))

    engine.queue_speech = queue_speech
    engine._active_agent.speak = speak
    engine._active_agent.run_llm = run_llm
    engine.context = MagicMock()
    return engine, calls


async def _open_start(engine, **kwargs):
    return await engine.queue_node_opening(
        node_id="start", previous_node_id=None, generate_if_no_greeting=True, **kwargs
    )


@pytest.mark.asyncio
async def test_disclosure_plays_before_the_greeting_exactly_once():
    engine, calls = _engine(CallDisclosureConfiguration(text=DISCLOSURE))

    result = await _open_start(engine)
    # Retries and re-entries of the start node never repeat it.
    await _open_start(engine)
    await engine.queue_node_opening(node_id="start", previous_node_id="end")

    spoken = [call[1] for call in calls]
    assert spoken == [RENDERED_DISCLOSURE] + ["Hi Ada, this is Sarah."] * 3
    _, _, disclosure_kwargs = calls[0]
    assert disclosure_kwargs == {
        "append_to_context": True,
        "persist_to_logs": True,
        "mute_user": True,
        "greeting": False,
    }
    assert calls[1][2]["greeting"] is True
    assert result.action == "greeting"


@pytest.mark.asyncio
async def test_disclosure_also_leads_a_generated_opening():
    engine, calls = _engine(CallDisclosureConfiguration(), greeting=None)
    engine.expect_response = MagicMock()

    result = await _open_start(engine)

    assert calls[0][1] == DEFAULT_CALL_DISCLOSURE_TEXT
    assert calls[1] == ("run_llm",)
    assert result.action == "llm"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "disclosure",
    [None, CallDisclosureConfiguration(enabled=False)],
    ids=["engine-without-setting", "disabled"],
)
async def test_disabled_disclosure_is_not_played(disclosure):
    engine, calls = _engine(disclosure)

    await _open_start(engine)

    assert [call[1] for call in calls] == ["Hi Ada, this is Sarah."]


@pytest.mark.asyncio
async def test_resumed_start_node_is_not_a_new_call():
    # A text-chat turn resumes its checkpointed node.
    engine, calls = _engine(CallDisclosureConfiguration())

    await engine.queue_node_opening(node_id="start", previous_node_id="start")
    # A later opening of the start node (an agent transfer that plays its
    # greeting) belongs to the same conversation.
    await engine.queue_node_opening(node_id="start", previous_node_id=None)

    assert [call[1] for call in calls] == ["Hi Ada, this is Sarah."]


@pytest.mark.asyncio
async def test_only_the_calls_first_opening_discloses():
    engine, calls = _engine(CallDisclosureConfiguration())

    await engine.queue_node_opening(node_id="end", previous_node_id=None)
    await _open_start(engine)

    assert DEFAULT_CALL_DISCLOSURE_TEXT not in [call[1] for call in calls]


@pytest.mark.asyncio
async def test_audio_disclosure_plays_the_recording():
    engine, calls = _engine(
        CallDisclosureConfiguration(type="audio", recording_id="ai_notice")
    )

    await _open_start(engine)

    assert [call[1] for call in calls] == ["ai_notice", "Hi Ada, this is Sarah."]
    assert calls[0][2]["mute_user"] is True
    assert calls[0][2]["greeting"] is False


@pytest.mark.asyncio
async def test_audio_disclosure_falls_back_to_text_when_the_recording_fails():
    engine, calls = _engine(
        CallDisclosureConfiguration(
            type="audio", recording_id="missing", text=DISCLOSURE
        ),
        failing_recordings=frozenset({"missing"}),
    )

    await _open_start(engine)

    assert [call[1] for call in calls] == [
        "missing",
        RENDERED_DISCLOSURE,
        "Hi Ada, this is Sarah.",
    ]
    assert calls[1][2]["mute_user"] is True


@pytest.mark.asyncio
async def test_realtime_text_disclosure_leads_the_spoken_greeting():
    engine, calls = _engine(
        CallDisclosureConfiguration(text=DISCLOSURE), is_realtime=True
    )

    await _open_start(engine)

    assert calls == [
        (
            "speak",
            f"{RENDERED_DISCLOSURE} Hi Ada, this is Sarah.",
            {"append_to_context": True, "persist_to_logs": False},
        )
    ]
    assert engine.speech_playback.greeting is None


@pytest.mark.asyncio
async def test_realtime_disclosure_is_the_opening_line_without_a_greeting():
    engine, calls = _engine(
        CallDisclosureConfiguration(), greeting=None, is_realtime=True
    )

    result = await _open_start(engine)

    assert [call[:2] for call in calls] == [("speak", DEFAULT_CALL_DISCLOSURE_TEXT)]
    assert result.action == "greeting"


@pytest.mark.asyncio
async def test_realtime_disclosure_is_spoken_before_a_recorded_greeting():
    engine, calls = _engine(
        CallDisclosureConfiguration(), greeting_type="audio", is_realtime=True
    )
    engine._open_realtime_after_recorded_greeting = AsyncMock()

    await _open_start(engine)

    assert [call[:2] for call in calls] == [
        ("speak", DEFAULT_CALL_DISCLOSURE_TEXT),
        ("queue_speech", 7),
    ]


@pytest.mark.asyncio
async def test_realtime_audio_disclosure_plays_before_the_model_speaks():
    engine, calls = _engine(
        CallDisclosureConfiguration(type="audio", recording_id="ai_notice"),
        is_realtime=True,
    )

    await _open_start(engine)

    assert [call[:2] for call in calls] == [
        ("queue_speech", "ai_notice"),
        ("speak", "Hi Ada, this is Sarah."),
    ]


class _RealtimeLLM:
    def __init__(self):
        self.set_opening_line = MagicMock()


@pytest.mark.parametrize(
    ("greeting", "expected"),
    [
        (GREETING, f"{RENDERED_DISCLOSURE} Hi Ada, this is Sarah."),
        (None, RENDERED_DISCLOSURE),
    ],
)
def test_realtime_opening_line_names_the_disclosure(greeting, expected):
    engine, _ = _engine(
        CallDisclosureConfiguration(text=DISCLOSURE),
        is_realtime=True,
        greeting=greeting,
    )
    llm = _RealtimeLLM()
    engine._active_agent.llm = llm
    start = engine._active_agent.workflow.nodes["start"]

    engine._hand_over_opening_line(engine._active_agent, start)

    llm.set_opening_line.assert_called_once_with(expected)


def test_realtime_opening_line_leaves_a_recorded_disclosure_out():
    engine, _ = _engine(
        CallDisclosureConfiguration(type="audio", recording_id="ai_notice"),
        is_realtime=True,
    )
    llm = _RealtimeLLM()
    engine._active_agent.llm = llm

    engine._hand_over_opening_line(
        engine._active_agent, engine._active_agent.workflow.nodes["start"]
    )

    llm.set_opening_line.assert_called_once_with("Hi Ada, this is Sarah.")


# ─── Supervised answering ───────────────────────────────────────


def _supervised(engine, verdicts, **settings):
    engine.drain_call_pipeline = AsyncMock(return_value=True)
    engine.end_call_with_reason = AsyncMock()
    supervisor = Mock()
    supervisor.config = AnswerSupervisorConfig(**settings)
    supervisor.wait_for_verdict = AsyncMock(side_effect=verdicts)
    supervisor.wait_for_human = AsyncMock(side_effect=asyncio.Event().wait)
    supervisor.wait_closed = AsyncMock(side_effect=asyncio.Event().wait)
    return supervisor


@pytest.mark.asyncio
async def test_supervised_call_discloses_once_a_human_is_detected():
    engine, calls = _engine(CallDisclosureConfiguration())
    supervisor = _supervised(
        engine,
        [
            AnswerVerdict(
                AnswerAction.SCREEN_THEN_REARM, "screener", MachineSubtype.SCREENER
            ),
            AnswerVerdict(
                AnswerAction.RELEASE, "human_turn", MachineSubtype.CONVERSATION
            ),
        ],
        screening_message=AnswerMessage(text="Alex calling about your appointment."),
    )

    await asyncio.wait_for(handle_answer(engine, supervisor), 1)

    # The screener hears only the screening reply; the human who picks up
    # hears the disclosure, then the greeting.
    assert [call[1] for call in calls] == [
        "Alex calling about your appointment.",
        DEFAULT_CALL_DISCLOSURE_TEXT,
        "Hi Ada, this is Sarah.",
    ]
    supervisor.release.assert_called_once()


@pytest.mark.asyncio
async def test_voicemail_gets_no_disclosure_when_the_opening_never_plays():
    engine, calls = _engine(CallDisclosureConfiguration())
    supervisor = _supervised(
        engine,
        [AnswerVerdict(AnswerAction.LEAVE_MESSAGE, "voicemail")],
        voicemail_message=AnswerMessage(text="Please call us back."),
    )

    await asyncio.wait_for(handle_answer(engine, supervisor), 1)

    assert [call[1] for call in calls] == ["Please call us back."]
