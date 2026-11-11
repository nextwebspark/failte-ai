"""Irish names said the Irish way: the lexicon, the pipeline TTS transform, the
speech-to-speech guide and the demo seed's speech. Pure (no database)."""

import array
import re

import pytest
from pipecat.frames.frames import TTSAudioRawFrame, TTSTextFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService

from api.services.pipecat import service_factory
from api.services.pipecat.speech_synthesis import synthesize_speech
from api.services.pronunciation import irish

# The user's list, as they wrote it: written name -> how it should sound.
USER_LIST = {
    "Aoife": "EE-fa",
    "Caoimhe": "KEE-va",
    "Sadhbh": "SIVE",
    "Siobhán": "shiv-AWN",
    "Niamh": "NEEV",
    "Saoirse": "SEER-sha",
    "Róisín": "ro-SHEEN",
    "Clodagh": "CLO-da",
    "Gráinne": "GRAW-nya",
    "Tadhg": "TIEG",
    "Cian": "KEE-an",
    "Oisín": "ush-EEN",
    "Domhnall": "DOH-nal",
    "Eoghan": "OH-en",
    "Daithí": "DAH-hee",
    "Cathal": "KA-hal",
    "Rian": "REE-an",
}


# --- the lexicon ------------------------------------------------------------------


def test_lexicon_is_large_and_has_no_clashing_spellings():
    assert len(irish.LEXICON) >= 150
    by_form, _ = irish._index()  # raises on a spelling listed twice
    assert len(by_form) > len(irish.LEXICON)


@pytest.mark.parametrize("entry", irish.LEXICON, ids=lambda e: e.spelling)
def test_every_entry_is_complete(entry):
    assert entry.say.strip() and entry.guide.strip()
    assert entry.kind in ("first_name", "surname", "place")
    # The respelling is plain English text a voice can read: no markup.
    assert not re.search(r"[<>\[\]{}/]", entry.say)
    if entry.ipa is not None:
        assert entry.ipa.strip() and not re.search(r"[A-Z]", entry.ipa)


@pytest.mark.parametrize(("name", "sound"), USER_LIST.items())
def test_the_users_list_is_in_the_lexicon(name, sound):
    entry = irish.lookup(name)
    assert entry is not None
    assert entry.guide.startswith(sound)


@pytest.mark.parametrize(
    ("written", "spelling"),
    [
        ("Siobhan", "Siobhán"),
        ("roisin", "Róisín"),
        ("OISIN", "Oisín"),
        ("Dun Laoghaire", "Dún Laoghaire"),
        ("Ó  Súilleabháin", "Ó Súilleabháin"),
        ("Meadhbh", "Méabh"),
    ],
)
def test_lookup_matches_with_and_without_fadas(written, spelling):
    assert irish.lookup(written).spelling == spelling


def test_bare_forms_that_are_other_names_are_not_matched():
    # "Tomas" is also a Lithuanian or Spanish name, "Pol" a Catalan one.
    assert irish.lookup("Tomás") is not None
    assert irish.lookup("Tomas") is None
    assert irish.lookup("Pol") is None
    assert irish.lookup("Colman") is None


def test_places_the_user_named_are_listed():
    for place in (
        "Dún Laoghaire",
        "Clonakilty",
        "Youghal",
        "Drogheda",
        "Naas",
        "Cobh",
        "Leixlip",
        "Portlaoise",
    ):
        assert irish.lookup(place).kind == "place"


# --- respelling -------------------------------------------------------------------


def test_respell_replaces_whole_names_only():
    text = "Thanks Aoife. Is that Aoife's booking for Naas, or Siobhan's?"
    assert irish.respell(text) == (
        "Thanks Eefa. Is that Eefa's booking for Nace, or Shiv-awn's?"
    )


def test_respell_leaves_longer_words_and_hyphenated_words_alone():
    assert irish.respell("Cianna, Niamhs, Aoife-Marie") == "Cianna, Niamhs, Aoife-Marie"


def test_respell_handles_multi_word_names_and_odd_spacing():
    assert irish.respell("Seán Ó  Néill from Dún Laoghaire") == (
        "Shawn Oh Nail from Dun Leery"
    )


def test_respell_keeps_text_without_names():
    text = "Your table for four is booked for 7pm on Friday."
    assert irish.respell(text) == text
    assert irish.respell("") == ""


@pytest.mark.asyncio
async def test_respell_transform_is_a_pipecat_text_transform():
    assert await irish.respell_transform("Hi Tadhg", "sentence") == "Hi Tyg"


# --- the speech-to-speech guide ---------------------------------------------------


def test_realtime_guide_has_the_core_names_and_the_names_in_the_call():
    guide = irish.realtime_guide(
        ["You answer the phone for a salon in Naas.", "Sorcha Ní Bhriain"]
    )
    assert guide.startswith("# SAYING IRISH NAMES")
    assert "Aoife = EE-fa" in guide
    assert "Naas = NACE" in guide
    assert "Sorcha = SUR-ka" in guide
    assert "Ní Bhriain = nee VREE-an" in guide
    # Each name once, and small: it rides along on every turn.
    assert guide.count("Aoife =") == 1
    assert len(guide) < 1500


def test_realtime_guide_respects_the_limit():
    many = " ".join(e.spelling for e in irish.LEXICON)
    guide = irish.realtime_guide([many], limit=20)
    assert guide.count(" = ") == 20


def test_realtime_guide_without_names_is_just_the_rule():
    guide = irish.realtime_guide(["no names here"], include_core=False)
    assert " = " not in guide and "Irish way" in guide


# --- pipeline TTS -----------------------------------------------------------------


PCM = b"\x01\x00" * 1600


class RecordingTTS(TTSService):
    """A TTS that records what it is asked to say and what it reports as said."""

    def __init__(self, **kwargs):
        super().__init__(
            sample_rate=16000,
            push_start_frame=True,
            push_stop_frames=True,
            settings=TTSSettings(model=None, voice=None, language=None),
            **kwargs,
        )
        self.synthesised: list[str] = []
        self.spoken_text: list[str] = []

    def can_generate_metrics(self) -> bool:
        return False

    async def run_tts(self, text, context_id):
        self.synthesised.append(text)
        yield TTSAudioRawFrame(PCM, 16000, 1, context_id=context_id)

    async def push_frame(self, frame, direction=FrameDirection.DOWNSTREAM):
        if isinstance(frame, TTSTextFrame):
            self.spoken_text.append(frame.text)
        await super().push_frame(frame, direction)


def _config(**tts):
    return type("Config", (), {"tts": type("TTS", (), tts)()})()


@pytest.mark.asyncio
async def test_pipeline_voice_hears_the_respelling_and_the_transcript_keeps_the_name():
    tts = RecordingTTS()
    service_factory._say_irish_names(tts, _config(language="en-US").tts)

    await synthesize_speech(tts, "Thanks Sadhbh, see you in Cobh.", timeout=5)

    assert tts.synthesised == ["Thanks Sive, see you in Cove."]
    assert "".join(tts.spoken_text).strip() == "Thanks Sadhbh, see you in Cobh."


@pytest.mark.parametrize(
    ("tts_config", "applied"),
    [
        ({"language": "en-IE"}, True),
        ({"language": None, "voice": "en-GB-Chirp3-HD-Kore"}, True),
        ({"language": None, "voice": "some-voice-id"}, True),
        ({"language": "multi"}, True),
        ({"language": "de-DE"}, False),
        ({"language": None, "voice": "fr-FR-Chirp3-HD-Charon"}, False),
    ],
)
def test_respelling_is_only_for_english_voices(tts_config, applied):
    tts = RecordingTTS()
    service_factory._say_irish_names(tts, _config(**tts_config).tts)
    assert (irish.respell_transform in [f for _, f in tts._text_transforms]) is applied


def test_word_timestamp_voices_are_left_alone():
    # Their transcript is rebuilt from the words the provider reports back,
    # which would be the respelling.
    tts = RecordingTTS(push_text_frames=False)
    service_factory._say_irish_names(tts, _config(language="en-US").tts)
    assert tts._text_transforms == []


def test_non_tts_objects_are_ignored():
    service_factory._say_irish_names(object(), _config(language="en-US").tts)


# --- the demo seed ----------------------------------------------------------------


def test_seed_speech_respells_names_and_reads_numbers_digit_by_digit():
    from api.scripts import seed_demo_accounts as seed

    assert seed.spoken("It's Caoimhe, on 087 555 0101.") == (
        "It's Keeva, on 0 8 7, 5 5 5, 0 1 0 1."
    )


def test_seed_trims_tts_silence_but_keeps_a_little_room():
    from api.scripts import seed_demo_accounts as seed

    rate = seed.SAMPLE_RATE
    speech = array.array("h", [3000, -3000] * (rate // 4)).tobytes()  # 0.5 s
    padded = seed._silence(0.45) + speech + seed._silence(0.25)
    trimmed = seed._trim(padded)
    seconds = len(trimmed) / 2 / rate
    room = seed.TRIM_LEAD_SECONDS + seed.TRIM_TAIL_SECONDS
    assert 0.5 <= seconds <= 0.5 + room + 0.011
    assert seed._trim(seed._silence(0.3)) == seed._silence(0.3)


def test_seed_turn_gaps_are_natural():
    from api.scripts import seed_demo_accounts as seed

    for who, words in (
        ("agent", "What time suits?"),
        ("caller", "Friday."),
        ("caller", "Do you cover Cobh?"),
    ):
        low, high = seed.turn_gap(who, words)
        assert 0.25 <= low <= high <= 0.6
    assert (
        seed.turn_gap("caller", "Is it open?")[0] > seed.turn_gap("caller", "Yes.")[0]
    )
