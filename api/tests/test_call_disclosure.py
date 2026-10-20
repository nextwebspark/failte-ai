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
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection
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
from api.services.pipecat.realtime.openai_realtime import (
    DograhOpenAIRealtimeLLMService,
)
from api.services.pipecat.realtime.static_greeting import (
    format_disclosure_for_new_party_prompt,
    format_open_after_disclosure_prompt,
)
from api.services.pipecat.speech_playback import PlaybackOutcome, SpeechPlaybackTracker
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
            (
                kwargs[key]
                for key in ("recording_id", "recording_pk", "audio")
                if key in kwargs
            ),
            text,
        )
        failed = source in failing_recordings
        calls.append(("queue_speech", source, kwargs))
        speech = engine.speech_playback.create(greeting=kwargs.get("greeting", False))
        speech.text = text if text is not None else f"Transcript of {source}."
        speech.finish(PlaybackOutcome.FAILED if failed else PlaybackOutcome.PLAYED)
        return speech

    async def speak(text, **kwargs):
        calls.append(("speak", text, kwargs))
        engine.speech_playback._expected_response.finish(PlaybackOutcome.PLAYED)

    async def run_llm(_context):
        calls.append(("run_llm",))

    async def queue_llm_frame(frame):
        # A realtime prompt the model answers out loud.
        calls.append(("prompt", frame.messages[0]["content"], frame.run_llm))
        expected = engine.speech_playback._expected_response
        if expected is not None:
            expected.finish(PlaybackOutcome.PLAYED)

    engine.queue_speech = queue_speech
    engine._active_agent.speak = speak
    engine._active_agent.run_llm = run_llm
    engine._active_agent.llm.queue_frame = queue_llm_frame
    engine.expect_response = MagicMock()
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
async def test_realtime_without_a_greeting_discloses_then_generates_the_opening():
    """Like a pipeline call: the disclosure, then the model's own opening."""
    engine, calls = _engine(
        CallDisclosureConfiguration(), greeting=None, is_realtime=True
    )

    result = await _open_start(engine)

    assert [call[:2] for call in calls] == [
        ("speak", DEFAULT_CALL_DISCLOSURE_TEXT),
        ("prompt", format_open_after_disclosure_prompt()),
    ]
    assert calls[1][2] is True  # run_llm: the model answers it out loud
    assert result.action == "llm"
    engine.expect_response.assert_called_once()


@pytest.mark.asyncio
async def test_realtime_disclosure_alone_when_nothing_is_generated():
    engine, calls = _engine(
        CallDisclosureConfiguration(), greeting=None, is_realtime=True
    )

    result = await engine.queue_node_opening(node_id="start", previous_node_id=None)

    assert [call[:2] for call in calls] == [("speak", DEFAULT_CALL_DISCLOSURE_TEXT)]
    assert result.action == "disclosure"


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


# ─── Who hears it ───────────────────────────────────────────────


def _verdict(action, reason="human_turn", subtype=MachineSubtype.CONVERSATION):
    return AnswerVerdict(action, reason, subtype)


@pytest.mark.asyncio
async def test_pickup_after_screening_hears_the_disclosure_again():
    """The provisional opening disclosed to a screener; the human who picks up
    after it hears the disclosure, muted, before the agent answers them."""
    engine, calls = _engine(CallDisclosureConfiguration())
    supervisor = _supervised(
        engine,
        [
            _verdict(AnswerAction.START_OPENING, "listening_window"),
            _verdict(
                AnswerAction.SCREEN_THEN_REARM, "screener", MachineSubtype.SCREENER
            ),
            _verdict(AnswerAction.RELEASE),
        ],
        screening_message=AnswerMessage(text="Alex calling about your appointment."),
    )

    await asyncio.wait_for(handle_answer(engine, supervisor), 1)

    assert [call[1] if len(call) > 1 else call[0] for call in calls] == [
        DEFAULT_CALL_DISCLOSURE_TEXT,
        "Hi Ada, this is Sarah.",
        "Alex calling about your appointment.",
        DEFAULT_CALL_DISCLOSURE_TEXT,
        "run_llm",
    ]
    replay = calls[3][2]
    assert replay["mute_user"] is True
    # Committed to context directly, ahead of the generation that answers the
    # human, and logged once by its playback.
    assert replay["append_to_context"] is False
    assert replay["persist_to_logs"] is True
    engine.context.add_message.assert_called_with(
        {"role": "assistant", "content": DEFAULT_CALL_DISCLOSURE_TEXT}
    )

    # Never a third time.
    await engine.disclose_to_released_party(new_party=True)
    assert len([c for c in calls if c[1:2] == (DEFAULT_CALL_DISCLOSURE_TEXT,)]) == 2


@pytest.mark.asyncio
async def test_provisional_opening_heard_by_the_released_human_is_not_repeated():
    engine, calls = _engine(CallDisclosureConfiguration())
    supervisor = _supervised(
        engine,
        [
            _verdict(AnswerAction.START_OPENING, "listening_window"),
            _verdict(AnswerAction.RELEASE, "opening_complete"),
        ],
    )

    await asyncio.wait_for(handle_answer(engine, supervisor), 1)

    assert [call[1] for call in calls] == [
        DEFAULT_CALL_DISCLOSURE_TEXT,
        "Hi Ada, this is Sarah.",
    ]


@pytest.mark.asyncio
async def test_cut_off_disclosure_is_played_again_once():
    engine, calls = _engine(CallDisclosureConfiguration())
    await _open_start(engine, mute_user=False)
    cut_off = engine.speech_playback.create()
    cut_off.finish(PlaybackOutcome.INTERRUPTED)
    engine._call_disclosure_speech = cut_off

    await engine.disclose_to_released_party(new_party=False)
    await engine.disclose_to_released_party(new_party=True)

    assert [call[1] for call in calls] == [
        DEFAULT_CALL_DISCLOSURE_TEXT,
        "Hi Ada, this is Sarah.",
        DEFAULT_CALL_DISCLOSURE_TEXT,
    ]


@pytest.mark.asyncio
async def test_realtime_pickup_after_screening_is_prompted_to_disclose():
    """A realtime session has spent its opening turn: the model is asked to
    say the disclosure before it answers the person now on the line."""
    engine, calls = _engine(
        CallDisclosureConfiguration(text=DISCLOSURE), is_realtime=True
    )
    await _open_start(engine)

    await engine.disclose_to_released_party(new_party=True)

    assert calls[-1] == (
        "prompt",
        format_disclosure_for_new_party_prompt(RENDERED_DISCLOSURE),
        True,
    )
    assert engine.speech_playback.pending == {}


@pytest.mark.parametrize("deciding", [True, False])
@pytest.mark.asyncio
async def test_disclosure_mutes_only_once_no_supervisor_is_listening(deciding):
    """Muting drops the VAD and transcription frames the answer supervisor
    classifies on, so it would miss a machine greeting over the disclosure."""
    engine, calls = _engine(CallDisclosureConfiguration())
    engine.answer_supervisor = SimpleNamespace(blocks_workflow=deciding)

    await _open_start(engine, mute_user=False)

    assert calls[0][1] == DEFAULT_CALL_DISCLOSURE_TEXT
    assert calls[0][2]["mute_user"] is (not deciding)


@pytest.mark.parametrize("deciding", [True, False])
@pytest.mark.asyncio
async def test_realtime_disclosure_mutes_only_once_no_supervisor_is_listening(
    deciding,
):
    engine, _ = _engine(CallDisclosureConfiguration(), is_realtime=True)
    engine.answer_supervisor = SimpleNamespace(blocks_workflow=deciding)
    mutes = []
    speak = engine._speak_realtime_opening

    async def record(agent, text, *, mute_user):
        mutes.append(mute_user)
        return await speak(agent, text, mute_user=mute_user)

    engine._speak_realtime_opening = record

    await _open_start(engine, mute_user=False)

    assert mutes == [not deciding]


# ─── Text fallbacks ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_blank_rendered_disclosure_says_the_default_notice():
    engine, calls = _engine(CallDisclosureConfiguration(text="{{missing}}"))

    await _open_start(engine)

    assert calls[0][1] == DEFAULT_CALL_DISCLOSURE_TEXT


@pytest.mark.asyncio
@pytest.mark.parametrize("is_realtime", [False, True])
async def test_recording_only_disclosure_says_the_default_when_it_cannot_play(
    is_realtime,
):
    disclosure = CallDisclosureConfiguration(
        type="audio", recording_id="missing", text=""
    )
    engine, calls = _engine(
        disclosure, failing_recordings=frozenset({"missing"}), is_realtime=is_realtime
    )
    # Text chat sends a recorded disclosure as its text.
    text_only, text_calls = _engine(disclosure.model_copy(update={"type": "text"}))

    await _open_start(engine)
    await _open_start(text_only)

    spoken = [call[1] for call in calls if call[0] in {"queue_speech", "speak"}]
    assert spoken[0] == "missing"
    assert spoken[1].startswith(DEFAULT_CALL_DISCLOSURE_TEXT)
    assert text_calls[0][1] == DEFAULT_CALL_DISCLOSURE_TEXT


def test_disclosure_text_is_short_enough_for_the_greeting_budget():
    assert MAX_CALL_DISCLOSURE_TEXT_LENGTH == 250


# ─── Ordering and budgets ───────────────────────────────────────


@pytest.mark.asyncio
async def test_disclosure_alone_is_reported_as_queued():
    """Text chat waits for queued output before adding a pending user
    message, so the disclosure must be reported even with nothing after it."""
    engine, calls = _engine(CallDisclosureConfiguration(), greeting=None)

    result = await engine.queue_node_opening(node_id="start", previous_node_id=None)

    assert [call[1] for call in calls] == [DEFAULT_CALL_DISCLOSURE_TEXT]
    assert result.action == "disclosure"
    assert result.playback is engine._call_disclosure_speech


@pytest.mark.asyncio
async def test_generated_opening_sees_the_disclosure_in_context():
    engine, calls = _engine(CallDisclosureConfiguration(), greeting=None)
    seen = []
    engine._active_agent.run_llm = AsyncMock(
        side_effect=lambda context: seen.append(
            [c.args[0] for c in context.add_message.call_args_list]
        )
    )

    await _open_start(engine)

    assert seen == [[{"role": "assistant", "content": DEFAULT_CALL_DISCLOSURE_TEXT}]]
    # The playback logs it but does not commit it a second time.
    assert calls[0][2]["append_to_context"] is False
    assert calls[0][2]["persist_to_logs"] is True


@pytest.mark.asyncio
async def test_supervised_opening_budget_grows_only_while_a_disclosure_is_owed():
    engine, _ = _engine(CallDisclosureConfiguration())
    assert engine.call_disclosure_pending()
    await _open_start(engine)
    assert not engine.call_disclosure_pending()

    disabled, _ = _engine(CallDisclosureConfiguration(enabled=False))
    assert not disabled.call_disclosure_pending()


@pytest.mark.asyncio
async def test_queued_speech_deadline_starts_after_the_speech_ahead_of_it():
    tracker = SpeechPlaybackTracker()
    disclosure = tracker.create(timeout=0.2)
    greeting = tracker.create(timeout=0.1)
    greeting.defer_deadline_until(disclosure)

    await asyncio.sleep(0.15)
    # Still waiting behind the disclosure, so its own budget has not started.
    assert not greeting.done
    disclosure.finish(PlaybackOutcome.PLAYED)
    await asyncio.sleep(0.05)
    assert not greeting.done
    await asyncio.sleep(0.1)
    assert greeting.outcome is PlaybackOutcome.TIMED_OUT


# ─── Realtime ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_realtime_waits_a_bounded_time_for_the_model_to_disclose(monkeypatch):
    monkeypatch.setattr(
        "api.services.workflow.pipecat_engine.CALL_DISCLOSURE_REALTIME_WAIT_SECONDS",
        0.05,
    )
    engine, calls = _engine(
        CallDisclosureConfiguration(), greeting_type="audio", is_realtime=True
    )
    engine._open_realtime_after_recorded_greeting = AsyncMock()

    async def silent_model(text, **kwargs):
        calls.append(("speak", text, kwargs))

    engine._active_agent.speak = silent_model

    await asyncio.wait_for(_open_start(engine), 1)

    assert [call[:2] for call in calls] == [
        ("speak", DEFAULT_CALL_DISCLOSURE_TEXT),
        ("queue_speech", 7),
    ]
    assert engine._call_disclosure_speech.outcome is PlaybackOutcome.TIMED_OUT
    assert not engine.speech_playback.mutes_user


@pytest.mark.asyncio
async def test_realtime_unfetchable_audio_disclosure_is_in_the_instructions():
    """Settled before the session opens: the instructions and the spoken
    opening both carry the disclosure text when its recording is unavailable."""
    engine, calls = _engine(
        CallDisclosureConfiguration(
            type="audio", recording_id="ai_notice", text=DISCLOSURE
        ),
        is_realtime=True,
    )
    engine._fetch_recording_audio = AsyncMock(return_value=None)
    llm = _RealtimeLLM()
    engine._active_agent.llm = llm
    engine._setup_llm_context = AsyncMock()
    start = engine._active_agent.workflow.nodes["start"]

    await engine._handle_start_node(start)
    await _open_start(engine)

    expected = f"{RENDERED_DISCLOSURE} Hi Ada, this is Sarah."
    llm.set_opening_line.assert_called_once_with(expected)
    assert calls == [
        ("speak", expected, {"append_to_context": True, "persist_to_logs": False})
    ]
    engine._fetch_recording_audio.assert_awaited_once_with(recording_id="ai_notice")


@pytest.mark.asyncio
async def test_realtime_audio_disclosure_is_fetched_once_before_the_session_opens():
    engine, calls = _engine(
        CallDisclosureConfiguration(type="audio", recording_id="ai_notice"),
        is_realtime=True,
    )
    recording = SimpleNamespace(audio=b"\x01\x00" * 160, transcript="AI notice.")
    engine._fetch_recording_audio = AsyncMock(return_value=recording)
    llm = _RealtimeLLM()
    engine._active_agent.llm = llm
    engine._setup_llm_context = AsyncMock()

    await engine._handle_start_node(engine._active_agent.workflow.nodes["start"])
    await _open_start(engine)

    llm.set_opening_line.assert_called_once_with("Hi Ada, this is Sarah.")
    assert calls[0][:2] == ("queue_speech", recording.audio)
    assert calls[0][2]["transcript"] == "AI notice."
    assert calls[1][:2] == ("speak", "Hi Ada, this is Sarah.")
    engine._fetch_recording_audio.assert_awaited_once()


@pytest.mark.asyncio
async def test_realtime_recorded_greeting_reaches_the_session_after_the_disclosure():
    """The model says the disclosure, which spends its opening turn; the
    recorded greeting that follows must still reach the open session, as a
    silent assistant item, without asking the model for another response."""
    engine, calls = _engine(
        CallDisclosureConfiguration(), greeting_type="audio", is_realtime=True
    )
    service = DograhOpenAIRealtimeLLMService(api_key="test")
    service.push_frame = AsyncMock()
    service.send_client_event = AsyncMock()
    service._api_session_ready = True
    service._context = engine.context = LLMContext()
    engine._active_agent.llm = service

    async def speak(text, **kwargs):
        calls.append(("speak", text, kwargs))
        await service.process_frame(TTSSpeakFrame(text), FrameDirection.DOWNSTREAM)
        engine.speech_playback._expected_response.finish(PlaybackOutcome.PLAYED)

    engine._active_agent.speak = speak

    await _open_start(engine)

    sent = [call.args[0] for call in service.send_client_event.await_args_list]
    responses = [i for i, event in enumerate(sent) if event.type == "response.create"]
    assert len(responses) == 1
    assert DEFAULT_CALL_DISCLOSURE_TEXT in sent[responses[0]].response.instructions
    items = [
        (i, event.item.role, event.item.content[0].text)
        for i, event in enumerate(sent)
        if event.type == "conversation.item.create"
    ]
    assert items[-1][1:] == ("assistant", "Transcript of 7.")
    assert items[-1][0] > responses[0]
