"""Platform-managed models: the stored choices and the catalog response.

A platform configuration holds choices only. Project, location and credentials
are never part of it: they are filled in from server settings when the
configuration is compiled, so nothing secret is stored per organization or
returned by the API.
"""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.services.configuration.platform import catalog
from api.services.configuration.platform.catalog import PlatformPipelineMode

# --- Stored configuration ----------------------------------------------------


def _require_allowed(value: str, allowed: frozenset[str], what: str) -> str:
    if value not in allowed:
        raise ValueError(f"{what} {value!r} is not offered on platform models")
    return value


class _Choice(BaseModel):
    # Rejecting unknown fields keeps keys (api_key, credentials, project_id,
    # location) out of stored platform configurations.
    model_config = ConfigDict(extra="forbid")


class PlatformRealtimeChoice(_Choice):
    model: str = catalog.DEFAULT_REALTIME_MODEL
    voice: str = catalog.DEFAULT_REALTIME_VOICE
    language: str = catalog.DEFAULT_REALTIME_LANGUAGE

    @field_validator("model")
    @classmethod
    def _model_allowed(cls, value: str) -> str:
        return _require_allowed(
            value, catalog.option_ids(catalog.REALTIME_MODELS), "Realtime model"
        )

    @field_validator("voice")
    @classmethod
    def _voice_allowed(cls, value: str) -> str:
        return _require_allowed(
            value, catalog.option_ids(catalog.REALTIME_VOICES), "Realtime voice"
        )

    @field_validator("language")
    @classmethod
    def _language_allowed(cls, value: str) -> str:
        return _require_allowed(
            value, frozenset(catalog.REALTIME_LANGUAGES), "Realtime language"
        )


class PlatformLLMChoice(_Choice):
    model: str = catalog.DEFAULT_LLM_MODEL
    temperature: float | None = Field(
        default=catalog.DEFAULT_LLM_TEMPERATURE,
        ge=catalog.LLM_TEMPERATURE_RANGE.min,
        le=catalog.LLM_TEMPERATURE_RANGE.max,
    )

    @field_validator("model")
    @classmethod
    def _model_allowed(cls, value: str) -> str:
        return _require_allowed(
            value, catalog.option_ids(catalog.LLM_MODELS), "LLM model"
        )


class PlatformSTTChoice(_Choice):
    model: str = catalog.DEFAULT_STT_MODEL
    language: str = catalog.DEFAULT_STT_LANGUAGE

    @field_validator("model")
    @classmethod
    def _model_allowed(cls, value: str) -> str:
        return _require_allowed(
            value, catalog.option_ids(catalog.STT_MODELS), "Speech-to-text model"
        )

    @model_validator(mode="after")
    def _language_served_by_model(self) -> Self:
        if self.language not in catalog.stt_model_languages(self.model):
            raise ValueError(
                f"Speech-to-text language {self.language!r} is not offered "
                f"on platform models for {self.model}"
            )
        return self


class PlatformTTSChoice(_Choice):
    model: str = catalog.DEFAULT_TTS_MODEL
    voice: str = catalog.DEFAULT_TTS_VOICE
    language: str = catalog.DEFAULT_TTS_LANGUAGE
    speed: float = Field(
        default=catalog.DEFAULT_TTS_SPEED,
        ge=catalog.TTS_SPEED_RANGE.min,
        le=catalog.TTS_SPEED_RANGE.max,
    )

    @field_validator("model")
    @classmethod
    def _model_allowed(cls, value: str) -> str:
        return _require_allowed(
            value, catalog.option_ids(catalog.TTS_MODELS), "Text-to-speech model"
        )

    @field_validator("language")
    @classmethod
    def _language_allowed(cls, value: str) -> str:
        return _require_allowed(
            value, frozenset(catalog.TTS_LANGUAGES), "Text-to-speech language"
        )

    @model_validator(mode="after")
    def _voice_matches_model_and_language(self) -> Self:
        locale = catalog.tts_voice_locale(self.model, self.voice)
        if locale is None:
            raise ValueError(
                f"Text-to-speech voice {self.voice!r} is not a {self.model} voice"
            )
        if locale != self.language:
            # Google rejects a synthesis whose language disagrees with the voice.
            raise ValueError(
                f"Text-to-speech voice {self.voice!r} speaks {locale}, "
                f"not {self.language}"
            )
        return self


class PlatformPipelineChoice(_Choice):
    llm: PlatformLLMChoice = Field(default_factory=PlatformLLMChoice)
    stt: PlatformSTTChoice = Field(default_factory=PlatformSTTChoice)
    tts: PlatformTTSChoice = Field(default_factory=PlatformTTSChoice)


class PlatformAIModelConfiguration(_Choice):
    pipeline_mode: PlatformPipelineMode = catalog.DEFAULT_PIPELINE_MODE
    realtime: PlatformRealtimeChoice | None = None
    pipeline: PlatformPipelineChoice | None = None

    @model_validator(mode="after")
    def _selected_block_present(self) -> Self:
        if (
            self.pipeline_mode is PlatformPipelineMode.REALTIME
            and self.realtime is None
        ):
            raise ValueError(
                "platform.realtime is required when pipeline_mode is realtime"
            )
        if (
            self.pipeline_mode is PlatformPipelineMode.PIPELINE
            and self.pipeline is None
        ):
            raise ValueError(
                "platform.pipeline is required when pipeline_mode is pipeline"
            )
        return self


def default_platform_configuration() -> PlatformAIModelConfiguration:
    """The configuration a new organization starts with."""
    return PlatformAIModelConfiguration(
        pipeline_mode=catalog.DEFAULT_PIPELINE_MODE,
        realtime=PlatformRealtimeChoice(),
    )


# --- Catalog response --------------------------------------------------------


class PlatformCatalogOption(BaseModel):
    id: str
    label: str
    description: str | None = None
    recommended: bool = False
    gender: str | None = None
    preview_url: str | None = None
    # Speech-to-text models: the languages this model accepts.
    languages: list[str] | None = None


class PlatformCatalogRange(BaseModel):
    min: float
    max: float
    step: float


class PlatformRealtimeDefaults(BaseModel):
    model: str
    voice: str
    language: str


class PlatformRealtimeCatalog(BaseModel):
    models: list[PlatformCatalogOption]
    voices: list[PlatformCatalogOption]
    languages: list[str]
    defaults: PlatformRealtimeDefaults


class PlatformLLMDefaults(BaseModel):
    model: str
    temperature: float | None


class PlatformLLMCatalog(BaseModel):
    models: list[PlatformCatalogOption]
    temperature_range: PlatformCatalogRange
    defaults: PlatformLLMDefaults


class PlatformSTTDefaults(BaseModel):
    model: str
    language: str


class PlatformSTTCatalog(BaseModel):
    models: list[PlatformCatalogOption]
    languages: list[str]
    defaults: PlatformSTTDefaults


class PlatformTTSDefaults(BaseModel):
    model: str
    voice: str
    language: str
    speed: float


class PlatformTTSCatalog(BaseModel):
    models: list[PlatformCatalogOption]
    languages: list[str]
    speed_range: PlatformCatalogRange
    # Provider id for GET /user/configurations/voices/{provider}.
    voice_catalog: str
    defaults: PlatformTTSDefaults


class PlatformPipelineCatalog(BaseModel):
    llm: PlatformLLMCatalog
    stt: PlatformSTTCatalog
    tts: PlatformTTSCatalog


class PlatformModeOption(BaseModel):
    id: PlatformPipelineMode
    label: str
    description: str
    recommended: bool = False


class PlatformModelCatalog(BaseModel):
    """Everything a customer may pick on platform models.

    Languages are BCP-47 codes; clients render their display names.
    """

    enabled: bool
    default_mode: PlatformPipelineMode
    modes: list[PlatformModeOption]
    realtime: PlatformRealtimeCatalog
    pipeline: PlatformPipelineCatalog


class ModelConfigurationV2Defaults(BaseModel):
    # Provider schemas for the legacy managed (MPS) and BYOK editors.
    dograh: dict[str, Any]
    byok: dict[str, Any]
    platform: PlatformModelCatalog
