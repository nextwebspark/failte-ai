"""Tests for the Google voice catalogue (api/saas/voice_catalog/google_voices.py).

The catalogue is ours, not upstream's: upstream serves voice lists from its
hosted MPS service, which has no Google voices. These tests pin the contract the
voice picker relies on — base language codes, region accents, normalised gender
— because getting any of them wrong makes the picker silently show nothing.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.saas.voice_catalog import google_voices

# A slice of what https://texttospeech.googleapis.com/v1/voices returns, kept
# small but covering every case the shaping code branches on.
GOOGLE_VOICES_PAYLOAD = {
    "voices": [
        {
            "name": "en-GB-Chirp3-HD-Aoede",
            "languageCodes": ["en-GB"],
            "ssmlGender": "FEMALE",
        },
        {
            "name": "en-US-Chirp3-HD-Aoede",
            "languageCodes": ["en-US"],
            "ssmlGender": "FEMALE",
        },
        {
            "name": "en-US-Chirp3-HD-Charon",
            "languageCodes": ["en-US"],
            "ssmlGender": "MALE",
        },
        {
            "name": "fr-FR-Chirp3-HD-Kore",
            "languageCodes": ["fr-FR"],
            "ssmlGender": "FEMALE",
        },
        # Google returns this for voices it declines to gender.
        {
            "name": "en-US-Standard-A",
            "languageCodes": ["en-US"],
            "ssmlGender": "SSML_VOICE_GENDER_UNSPECIFIED",
        },
    ]
}


@pytest.fixture(autouse=True)
def _fresh_caches(tmp_path, monkeypatch):
    """Each test gets an empty catalogue/credential cache and a private
    preview directory, so nothing passes on a warm cache or touches the real
    filesystem cache."""
    monkeypatch.setattr(google_voices, "_catalogue_cache", {})
    monkeypatch.setattr(google_voices, "_credentials_cache", {})
    monkeypatch.setattr(google_voices, "PREVIEW_CACHE", tmp_path / "previews")


def _mock_http(payload=GOOGLE_VOICES_PAYLOAD, status_code=200):
    """Patch out the credential refresh and the voices HTTP call."""
    response = SimpleNamespace(status_code=status_code, json=lambda: payload, text="")
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return (
        patch.object(
            google_voices, "_credentials", return_value=SimpleNamespace(token="tok")
        ),
        patch.object(google_voices.httpx, "AsyncClient", return_value=client),
    )


async def _list(**kwargs):
    creds_patch, http_patch = _mock_http()
    with creds_patch, http_patch:
        return await google_voices.list_voices(**kwargs)


async def test_language_is_the_base_code_and_accent_carries_the_region():
    """The picker filters on ISO-639-1 and keys its display names that way.

    Emitting the raw locale ("en-GB") instead makes the picker's default
    language filter match zero voices — the bug this shaping exists to avoid.
    """
    result = await _list()
    by_id = {v["voice_id"]: v for v in result["voices"]}

    assert by_id["en-GB-Chirp3-HD-Aoede"]["language"] == "en"
    assert by_id["en-GB-Chirp3-HD-Aoede"]["accent"] == "gb"
    assert by_id["fr-FR-Chirp3-HD-Kore"]["language"] == "fr"
    assert by_id["fr-FR-Chirp3-HD-Kore"]["accent"] == "fr"


async def test_gender_is_normalised_so_it_never_reaches_a_filter_dropdown_raw():
    result = await _list()

    genders = {v["voice_id"]: v["gender"] for v in result["voices"]}
    assert genders["en-US-Chirp3-HD-Aoede"] == "female"
    assert genders["en-US-Chirp3-HD-Charon"] == "male"
    assert genders["en-US-Standard-A"] == "neutral"
    assert "ssml_voice_gender_unspecified" not in result["facets"]["genders"]


async def test_name_is_the_short_name_and_description_carries_the_label():
    """The picker renders its own accent/gender/language line under the name,
    so a human label in the name would just be repeated back."""
    result = await _list()
    aoede = next(
        v for v in result["voices"] if v["voice_id"] == "en-GB-Chirp3-HD-Aoede"
    )

    assert aoede["name"] == "Aoede"
    assert aoede["description"] == "British female · Chirp3-HD"
    assert aoede["preview_url"] == (
        "/api/v1/user/configurations/voices/google/preview"
        "?voice_id=en-GB-Chirp3-HD-Aoede"
    )


async def test_filters_are_combined():
    result = await _list(language="en", accent="gb", gender="female")

    assert [v["voice_id"] for v in result["voices"]] == ["en-GB-Chirp3-HD-Aoede"]


async def test_search_matches_the_voice_id_not_only_the_short_name():
    """The short name loses the locale, so a caller searching "en-GB" has only
    the id to match against."""
    result = await _list(q="en-GB")

    assert [v["voice_id"] for v in result["voices"]] == ["en-GB-Chirp3-HD-Aoede"]


async def test_model_selects_a_voice_family():
    result = await _list(model="chirp_3_hd")

    assert all("Chirp3-HD" in v["voice_id"] for v in result["voices"])
    assert "en-US-Standard-A" not in {v["voice_id"] for v in result["voices"]}


async def test_facets_describe_the_whole_catalogue_not_the_filtered_view():
    """Otherwise the dropdowns collapse to whatever is already selected and the
    user cannot get back out of a filter."""
    result = await _list(language="fr")

    assert [v["voice_id"] for v in result["voices"]] == ["fr-FR-Chirp3-HD-Kore"]
    assert set(result["facets"]["languages"]) == {"en", "fr"}
    assert set(result["facets"]["accents"]) == {"gb", "us", "fr"}


async def test_upstream_failure_is_not_swallowed():
    creds_patch, http_patch = _mock_http(payload={}, status_code=403)
    with (
        creds_patch,
        http_patch,
        pytest.raises(RuntimeError, match="google voices api 403"),
    ):
        await google_voices.list_voices()


@pytest.mark.parametrize(
    "voice_id",
    ["../../etc/passwd", "en-US-Chirp3-HD-Aoede; rm -rf /", "ab", "x" * 65, ""],
)
async def test_preview_rejects_a_voice_id_that_is_not_a_voice_id(voice_id):
    """voice_id reaches a cache filename and an outbound request, so the guard
    is load-bearing, not cosmetic."""
    with pytest.raises(google_voices.InvalidVoiceIdError, match="invalid voice id"):
        await google_voices.preview_audio(voice_id)


async def test_catalogue_is_cached_between_calls():
    """The picker refetches on every debounced keystroke; each fetch must not
    cost a token mint plus a full ~1,568-voice download."""
    creds_patch, http_patch = _mock_http()
    with creds_patch as creds_mock, http_patch as client_mock:
        await google_voices.list_voices()
        await google_voices.list_voices(language="fr")

    assert client_mock.call_count == 1
    assert creds_mock.call_count == 1


async def test_catalogue_cache_expires():
    creds_patch, http_patch = _mock_http()
    with creds_patch, http_patch as client_mock:
        await google_voices.list_voices()
        key = next(iter(google_voices._catalogue_cache))
        cached_at, entries = google_voices._catalogue_cache[key]
        google_voices._catalogue_cache[key] = (
            cached_at - google_voices.CATALOGUE_TTL_SECONDS - 1,
            entries,
        )
        await google_voices.list_voices()

    assert client_mock.call_count == 2


def _mock_synthesize(audio: bytes = b"mp3-bytes"):
    import base64

    payload = {"audioContent": base64.b64encode(audio).decode()}
    response = SimpleNamespace(status_code=200, json=lambda: payload, text="")
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return (
        patch.object(
            google_voices, "_credentials", return_value=SimpleNamespace(token="tok")
        ),
        patch.object(google_voices.httpx, "AsyncClient", return_value=client),
        client,
    )


async def test_preview_is_synthesised_once_then_served_from_disk():
    creds_patch, http_patch, client = _mock_synthesize()
    with creds_patch, http_patch:
        first = await google_voices.preview_audio("en-GB-Chirp3-HD-Aoede")
        second = await google_voices.preview_audio("en-GB-Chirp3-HD-Aoede")

    assert first == second == b"mp3-bytes"
    client.post.assert_awaited_once()


async def test_preview_cache_write_failure_still_returns_audio(tmp_path, monkeypatch):
    """A cache-write problem is not a synthesis failure — the user still gets
    their preview."""
    # A regular file where the cache directory should be makes mkdir raise
    # NotADirectoryError, an OSError the write path must swallow.
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"")
    monkeypatch.setattr(google_voices, "PREVIEW_CACHE", blocker / "previews")

    creds_patch, http_patch, _ = _mock_synthesize()
    with creds_patch, http_patch:
        audio = await google_voices.preview_audio("en-GB-Chirp3-HD-Aoede")

    assert audio == b"mp3-bytes"
