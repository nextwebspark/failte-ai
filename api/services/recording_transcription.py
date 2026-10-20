"""Transcribe uploaded prompt recordings.

Platform-models servers transcribe on the operator's own Google
Speech-to-Text (Chirp 3, in PLATFORM_GOOGLE_SPEECH_LOCATION, "eu" by default).
Otherwise the configured MPS does it. With neither, transcription is not
available and the caller asks the user to type the transcript.
"""

from __future__ import annotations

import io
import json
import wave

from api import constants
from api.services.configuration.platform.languages import CHIRP_3_LANGUAGES
from api.services.configuration.platform.policy import (
    platform_settings_for_organization,
)
from api.services.mps_service_key_client import mps_service_key_client

PLATFORM_TRANSCRIPTION_MODEL = "chirp_3"
# Chirp 3 detects the spoken language itself when asked for "auto".
_AUTO_LANGUAGE = "auto"
_CHIRP_3_LANGUAGES = frozenset(CHIRP_3_LANGUAGES)
# Synchronous recognize accepts about a minute of audio; stay under it.
MAX_PLATFORM_TRANSCRIPTION_SECONDS = 55


class TranscriptionUnavailableError(Exception):
    """No speech-to-text service is configured on this server."""


class RecordingTooLongError(Exception):
    """The recording is longer than synchronous recognition accepts."""


def transcription_available() -> bool:
    return constants.PLATFORM_MODELS_ENABLED or mps_service_key_client.is_configured


def _platform_language_code(language: str | None) -> str:
    """Map the recordings dialog's language choice to a Chirp 3 language code.

    The dialog offers "multi" plus Deepgram-style codes, several without a
    region ("en"); Chirp 3 needs a locale it supports, so anything else
    falls back to automatic detection.
    """
    if language and language in _CHIRP_3_LANGUAGES:
        return language
    return _AUTO_LANGUAGE


def _wav_duration_seconds(audio_data: bytes) -> float | None:
    """The duration of a WAV recording, or None when it is not a readable WAV."""
    try:
        with wave.open(io.BytesIO(audio_data)) as wav:
            rate = wav.getframerate()
            return wav.getnframes() / rate if rate else None
    except (wave.Error, EOFError):
        return None


async def _transcribe_with_platform_speech(
    audio_data: bytes, language: str, organization_id: int | None
) -> dict:
    from google.api_core.client_options import ClientOptions
    from google.cloud.speech_v2 import SpeechAsyncClient
    from google.cloud.speech_v2.types import cloud_speech
    from google.oauth2 import service_account

    settings = await platform_settings_for_organization(organization_id)
    location = settings.speech_location
    credentials = (
        service_account.Credentials.from_service_account_info(
            json.loads(settings.credentials_json)
        )
        if settings.credentials_json
        else None  # Application Default Credentials
    )
    async with SpeechAsyncClient(
        credentials=credentials,
        client_options=(
            ClientOptions(api_endpoint=f"{location}-speech.googleapis.com")
            if location != "global"
            else None
        ),
    ) as client:
        response = await client.recognize(
            request=cloud_speech.RecognizeRequest(
                recognizer=(
                    f"projects/{settings.project_id}/locations/{location}/recognizers/_"
                ),
                config=cloud_speech.RecognitionConfig(
                    auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
                    model=PLATFORM_TRANSCRIPTION_MODEL,
                    language_codes=[_platform_language_code(language)],
                    features=cloud_speech.RecognitionFeatures(
                        enable_automatic_punctuation=True,
                    ),
                ),
                content=audio_data,
            )
        )
    transcript = " ".join(
        result.alternatives[0].transcript.strip()
        for result in response.results
        if result.alternatives and result.alternatives[0].transcript.strip()
    )
    return {"transcript": transcript}


async def transcribe_recording(
    *,
    audio_data: bytes,
    filename: str,
    content_type: str,
    language: str,
    organization_id: int | None,
    created_by: str,
) -> dict:
    """Return ``{"transcript": ...}`` for an uploaded recording.

    Raises TranscriptionUnavailableError when no speech-to-text is configured,
    and RecordingTooLongError when a WAV recording is too long for the
    platform's synchronous recognition (Google is not called).
    """
    if constants.PLATFORM_MODELS_ENABLED:
        duration = _wav_duration_seconds(audio_data)
        if duration is not None and duration > MAX_PLATFORM_TRANSCRIPTION_SECONDS:
            raise RecordingTooLongError(
                f"Recording is {duration:.0f}s; platform transcription accepts "
                f"up to {MAX_PLATFORM_TRANSCRIPTION_SECONDS}s"
            )
        return await _transcribe_with_platform_speech(
            audio_data, language, organization_id
        )
    if not mps_service_key_client.is_configured:
        raise TranscriptionUnavailableError()
    if constants.DEPLOYMENT_MODE == "oss":
        return await mps_service_key_client.transcribe_audio(
            audio_data=audio_data,
            filename=filename,
            content_type=content_type,
            language=language,
            created_by=created_by,
        )
    return await mps_service_key_client.transcribe_audio(
        audio_data=audio_data,
        filename=filename,
        content_type=content_type,
        language=language,
        organization_id=organization_id,
    )
