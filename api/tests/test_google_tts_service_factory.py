from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pipecat.services.settings import NOT_GIVEN

from api.services.configuration.registry import ServiceProviders
from api.services.pipecat.service_factory import create_tts_service


def test_create_google_tts_service_uses_credentials_location_and_settings():
    user_config = SimpleNamespace(
        tts=SimpleNamespace(
            provider=ServiceProviders.GOOGLE.value,
            credentials='{"project_id":"demo-project"}',
            api_key=None,
            model="chirp_3_hd",
            voice="en-US-Chirp3-HD-Charon",
            language="en-US",
            speed=1.15,
            location="us-central1",
        )
    )
    audio_config = SimpleNamespace(
        transport_out_sample_rate=24000,
        transport_in_sample_rate=16000,
    )

    with patch("api.services.pipecat.service_factory.GoogleTTSService") as mock_service:
        create_tts_service(user_config, audio_config)

    assert mock_service.call_count == 1
    kwargs = mock_service.call_args.kwargs
    assert kwargs["credentials"] == '{"project_id":"demo-project"}'
    assert kwargs["location"] == "us-central1"
    assert kwargs["settings"].model == "chirp_3_hd"
    assert kwargs["settings"].voice == "en-US-Chirp3-HD-Charon"
    assert kwargs["settings"].language == "en-US"
    assert kwargs["settings"].speaking_rate == 1.15


def test_create_google_tts_service_omits_default_speed():
    user_config = SimpleNamespace(
        tts=SimpleNamespace(
            provider=ServiceProviders.GOOGLE.value,
            credentials=None,
            api_key=None,
            model="chirp_3_hd",
            # Was en-US-Chirp3-HD-Charon against language sw-KE — the pair
            # Google rejects at runtime. The language now comes from the voice,
            # so the fixture has to be a pair that could actually be synthesised.
            voice="sw-KE-Chirp3-HD-Charon",
            language="sw-KE",
            speed=1.0,
            location=None,
        )
    )
    audio_config = SimpleNamespace(
        transport_out_sample_rate=24000,
        transport_in_sample_rate=16000,
    )

    with patch("api.services.pipecat.service_factory.GoogleTTSService") as mock_service:
        create_tts_service(user_config, audio_config)

    assert mock_service.call_count == 1
    kwargs = mock_service.call_args.kwargs
    assert kwargs["location"] is None
    assert kwargs["settings"].model == "chirp_3_hd"
    assert kwargs["settings"].language == "sw-KE"
    assert kwargs["settings"].speaking_rate is NOT_GIVEN


# --- Language derived from the voice ----------------------------------------
#
# Google's synthesis call takes language_code and voice separately and rejects
# them if they disagree, but the two are configured independently, so the pair
# is easy to get wrong from the voice picker. The voice decides.


AUDIO_CONFIG = SimpleNamespace(
    transport_out_sample_rate=24000,
    transport_in_sample_rate=16000,
)


def _google_settings(**tts):
    defaults = {
        "provider": ServiceProviders.GOOGLE.value,
        "credentials": None,
        "api_key": None,
        "model": "chirp_3_hd",
        "voice": "en-US-Chirp3-HD-Charon",
        "language": "en-US",
        "speed": None,
        "location": None,
    }
    user_config = SimpleNamespace(tts=SimpleNamespace(**{**defaults, **tts}))

    with patch("api.services.pipecat.service_factory.GoogleTTSService") as mock_service:
        create_tts_service(user_config, AUDIO_CONFIG)

    assert mock_service.call_count == 1
    return mock_service.call_args.kwargs["settings"]


@pytest.mark.parametrize(
    "voice,expected",
    [
        ("en-GB-Chirp3-HD-Aoede", "en-GB"),
        ("en-US-Chirp3-HD-Aoede", "en-US"),
        ("fr-FR-Chirp3-HD-Kore", "fr-FR"),
        # Three-letter language subtags are real: Mandarin, Cantonese, Filipino.
        ("cmn-CN-Chirp3-HD-Kore", "cmn-CN"),
    ],
)
def test_language_comes_from_the_voice_locale(voice, expected):
    """Configured "en-GB" with an en-US voice is a 400 from Google."""
    settings = _google_settings(voice=voice, language="en-GB")

    assert settings.voice == voice
    assert settings.language == expected


def test_configured_language_survives_a_voice_that_carries_no_locale():
    settings = _google_settings(voice="Charon", language="en-GB")

    assert settings.language == "en-GB"


def test_google_tts_defaults_are_self_consistent():
    settings = _google_settings(voice=None, language=None)

    assert settings.voice == "en-US-Chirp3-HD-Charon"
    assert settings.language == "en-US"
    assert settings.model == "chirp_3_hd"
