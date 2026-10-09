"""The curated list of models, voices and languages offered on platform models.

This is the server-side allowlist: the UI renders whatever is listed here, and
stored platform configurations are validated against it. Every entry must run
inside the EU on the operator's Vertex project, which is why Vertex MaaS models
(served from us-central1) and Gemini models that only exist at the "global"
location are left out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from api.services.configuration.options.google import (
    GOOGLE_VERTEX_REALTIME_LANGUAGES,
)
from api.services.configuration.platform.languages import (
    CHIRP_3_HD_LOCALES,
    CHIRP_3_LANGUAGES,
    LATEST_LONG_LANGUAGES,
    LATEST_SHORT_LANGUAGES,
)


class PlatformPipelineMode(StrEnum):
    """How a platform-managed agent talks."""

    REALTIME = "realtime"
    PIPELINE = "pipeline"


@dataclass(frozen=True, slots=True)
class PlatformOption:
    """One selectable entry (model, voice or language) in the catalog."""

    id: str
    label: str
    description: str | None = None
    recommended: bool = False
    gender: str | None = None
    preview_url: str | None = None
    # For speech-to-text models: the languages this model accepts.
    languages: tuple[str, ...] | None = None
    # For text-to-speech models: the family token in the model's voice names,
    # which are "<locale>-<family>-<Name>".
    voice_family: str | None = None


@dataclass(frozen=True, slots=True)
class NumericRange:
    min: float
    max: float
    step: float


GOOGLE_VOICE_PREVIEW_PATH: Final = "/api/v1/user/configurations/voices/google/preview"


def google_voice_preview_url(voice_name: str) -> str:
    return f"{GOOGLE_VOICE_PREVIEW_PATH}?voice_id={voice_name}"


# --- Speech-to-speech (Gemini Live on Vertex) --------------------------------

REALTIME_MODELS: Final[tuple[PlatformOption, ...]] = (
    PlatformOption(
        id="google/gemini-live-2.5-flash-native-audio",
        label="Gemini Live 2.5 Flash",
        description="Natural, low-latency native audio conversation.",
        recommended=True,
    ),
)


def _live_voice(name: str, gender: str, description: str) -> PlatformOption:
    # Gemini Live voices share their names and timbre with the Chirp 3 HD
    # voices, so the Chirp 3 HD sample is a faithful preview.
    return PlatformOption(
        id=name,
        label=name,
        description=description,
        gender=gender,
        preview_url=google_voice_preview_url(f"en-US-Chirp3-HD-{name}"),
    )


REALTIME_VOICES: Final[tuple[PlatformOption, ...]] = (
    _live_voice("Charon", "male", "Informative"),
    _live_voice("Puck", "male", "Upbeat"),
    _live_voice("Fenrir", "male", "Excitable"),
    _live_voice("Kore", "female", "Firm"),
    _live_voice("Aoede", "female", "Breezy"),
)

REALTIME_LANGUAGES: Final[tuple[str, ...]] = tuple(GOOGLE_VERTEX_REALTIME_LANGUAGES)

# --- Pipeline: LLM ------------------------------------------------------------

LLM_MODELS: Final[tuple[PlatformOption, ...]] = (
    PlatformOption(
        id="gemini-3.5-flash",
        label="Gemini 3.5 Flash",
        description="Best balance of reliability and speed for calls.",
        recommended=True,
    ),
    PlatformOption(
        id="gemini-3.1-flash-lite",
        label="Gemini 3.1 Flash Lite",
        description="Fastest and cheapest; best for simple flows.",
    ),
)

# Offered only to organizations a superuser enables them for (#49).
RESTRICTED_LLM_MODELS: Final[tuple[PlatformOption, ...]] = (
    PlatformOption(
        id="gemini-3.5-flash-lite",
        label="Gemini 3.5 Flash Lite",
        description=(
            "Lowest latency. Can skip end-call and number confirmation on "
            "complex flows; test the agent before switching."
        ),
    ),
)

LLM_TEMPERATURE_RANGE: Final = NumericRange(min=0.0, max=2.0, step=0.1)

# --- Pipeline: speech-to-text -------------------------------------------------

STT_MODELS: Final[tuple[PlatformOption, ...]] = (
    PlatformOption(
        id="chirp_3",
        label="Chirp 3",
        description="Most accurate, multilingual recognition.",
        recommended=True,
        languages=CHIRP_3_LANGUAGES,
    ),
    PlatformOption(
        id="latest_long",
        label="Latest long",
        description="Tuned for long-form conversation.",
        languages=LATEST_LONG_LANGUAGES,
    ),
    PlatformOption(
        id="latest_short",
        label="Latest short",
        description="Tuned for short commands and replies.",
        languages=LATEST_SHORT_LANGUAGES,
    ),
)

STT_LANGUAGES: Final[tuple[str, ...]] = tuple(
    sorted({language for model in STT_MODELS for language in model.languages or ()})
)

# --- Pipeline: text-to-speech -------------------------------------------------

TTS_MODELS: Final[tuple[PlatformOption, ...]] = (
    PlatformOption(
        id="chirp_3_hd",
        label="Chirp 3 HD",
        description="Natural, expressive streaming voices.",
        recommended=True,
        voice_family="Chirp3-HD",
    ),
)

TTS_LANGUAGES: Final[tuple[str, ...]] = CHIRP_3_HD_LOCALES
TTS_SPEED_RANGE: Final = NumericRange(min=0.25, max=2.0, step=0.05)
# The UI picks voices from the Google voice catalog endpoint.
TTS_VOICE_CATALOG: Final = "google"

# Voice names carry the model family: "<locale>-Chirp3-HD-<Name>".
_TTS_VOICE_PATTERN: Final = {
    option.id: re.compile(
        rf"^(?P<locale>[a-z]{{2,3}}-[A-Z]{{2}})-{re.escape(option.voice_family)}-[A-Za-z]+$"
    )
    for option in TTS_MODELS
    if option.voice_family
}

# --- Defaults ----------------------------------------------------------------

DEFAULT_PIPELINE_MODE: Final = PlatformPipelineMode.REALTIME
DEFAULT_REALTIME_MODEL: Final = "google/gemini-live-2.5-flash-native-audio"
DEFAULT_REALTIME_VOICE: Final = "Charon"
DEFAULT_REALTIME_LANGUAGE: Final = "en"
DEFAULT_LLM_MODEL: Final = "gemini-3.5-flash"
DEFAULT_LLM_TEMPERATURE: Final = 0.1
DEFAULT_STT_MODEL: Final = "chirp_3"
DEFAULT_STT_LANGUAGE: Final = "en-US"
DEFAULT_TTS_MODEL: Final = "chirp_3_hd"
DEFAULT_TTS_VOICE: Final = "en-US-Chirp3-HD-Charon"
DEFAULT_TTS_LANGUAGE: Final = "en-US"
DEFAULT_TTS_SPEED: Final = 1.0


def option_ids(options: tuple[PlatformOption, ...]) -> frozenset[str]:
    return frozenset(option.id for option in options)


def stt_model_languages(model: str) -> frozenset[str]:
    for option in STT_MODELS:
        if option.id == model:
            return frozenset(option.languages or ())
    return frozenset()


def tts_voice_locale(model: str, voice: str) -> str | None:
    """Return the voice's locale if *voice* belongs to TTS *model*, else None."""
    pattern = _TTS_VOICE_PATTERN.get(model)
    if pattern is None:
        return None
    match = pattern.match(voice)
    return match.group("locale") if match else None
