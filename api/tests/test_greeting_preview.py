"""The words an agent's voice preview reads, and how its audio is cached."""

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.saas.voice_catalog import google_voices
from api.services.workflow.greeting_preview import (
    MAX_PREVIEW_CHARS,
    fill_greeting,
    greeting_preview_text,
    is_preview_voice,
    shorten,
    start_greeting,
)


def _definition(**data):
    return {
        "nodes": [
            {"id": "a", "type": "agentNode", "data": {"prompt": "x"}},
            {"id": "s", "type": "startCall", "data": {"is_start": True, **data}},
        ]
    }


def test_reads_the_start_steps_spoken_greeting():
    assert start_greeting(_definition(greeting="  Hello there.  ")) == "Hello there."


def test_a_recorded_or_missing_greeting_has_no_text():
    recorded = _definition(
        greeting="Hi", greeting_type="audio", greeting_recording_id="rec-1"
    )
    assert start_greeting(recorded) is None
    assert start_greeting(_definition(greeting="   ")) is None
    assert start_greeting(_definition()) is None
    assert start_greeting({"nodes": "nope"}) is None
    assert start_greeting(None) is None


def test_fills_facts_and_drops_per_call_placeholders():
    text = (
        "Hi, thanks for calling {{initial_context.business_name}} , "
        "{{ initial_context.missing }} how can I help {{caller_name}}?"
    )
    assert (
        fill_greeting(text, {"business_name": " Bia Bistro "})
        == "Hi, thanks for calling Bia Bistro, how can I help?"
    )


def test_a_long_greeting_is_cut_at_a_sentence():
    first = "Hello and welcome. " * 10
    text = first + "x" * 400
    cut = shorten(text)
    assert len(cut) <= MAX_PREVIEW_CHARS
    assert cut.endswith("welcome.")


def test_a_long_greeting_without_sentences_is_cut_at_a_word():
    cut = shorten("word " * 100)
    assert len(cut) <= MAX_PREVIEW_CHARS
    assert cut.endswith("word")


def test_short_text_is_kept_whole():
    assert shorten("Hi.") == "Hi."


def test_preview_text_is_none_when_nothing_is_spoken():
    assert greeting_preview_text(_definition(greeting="{{caller_name}}"), {}) is None
    assert (
        greeting_preview_text(
            _definition(greeting="Hi, {{initial_context.business_name}} here."),
            {"business_name": "Bia"},
        )
        == "Hi, Bia here."
    )


@pytest.mark.parametrize(
    ("voice_id", "ok"),
    [
        ("en-GB-Chirp3-HD-Kore", True),
        ("en-IE-Chirp3-HD-Aoede", True),
        ("en-US-Neural2-A", False),
        ("Kore", False),
        ("en-GB-Chirp3-HD-../x", False),
    ],
)
def test_only_platform_voices_are_previewed(voice_id, ok):
    assert is_preview_voice(voice_id) is ok


def test_cache_key_is_per_voice_and_text_and_default_is_unchanged():
    voice = "en-GB-Chirp3-HD-Kore"
    default = google_voices.preview_cache_path(voice)
    assert default == google_voices.preview_cache_path(
        voice, google_voices.PREVIEW_TEXT
    )
    assert google_voices.preview_cache_path(voice, "Hi.") != default
    assert google_voices.preview_cache_path("en-GB-Chirp3-HD-Puck", "Hi.") != (
        google_voices.preview_cache_path(voice, "Hi.")
    )


@pytest.fixture
def preview_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(google_voices, "PREVIEW_CACHE", tmp_path / "previews")


@pytest.mark.asyncio
async def test_each_greeting_and_voice_is_synthesised_once(preview_cache):
    payload = {"audioContent": base64.b64encode(b"mp3").decode()}
    response = SimpleNamespace(status_code=200, json=lambda: payload, text="")
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    voice = "en-GB-Chirp3-HD-Kore"
    with (
        patch.object(
            google_voices, "_credentials", return_value=SimpleNamespace(token="t")
        ),
        patch.object(google_voices.httpx, "AsyncClient", return_value=client),
    ):
        assert await google_voices.cached_preview(voice, "Hi there.") is None
        await google_voices.preview_audio(voice, text="Hi there.")
        await google_voices.preview_audio(voice, text="Hi there.")
        assert await google_voices.cached_preview(voice, "Hi there.") == b"mp3"

    client.post.assert_awaited_once()
    assert client.post.await_args.kwargs["json"]["input"]["text"] == "Hi there."
