"""Build the platform catalog that the Models page renders."""

from __future__ import annotations

from api.schemas.platform_models import (
    PlatformCatalogOption,
    PlatformCatalogRange,
    PlatformLLMCatalog,
    PlatformLLMDefaults,
    PlatformModelCatalog,
    PlatformModeOption,
    PlatformPipelineCatalog,
    PlatformRealtimeCatalog,
    PlatformRealtimeDefaults,
    PlatformSTTCatalog,
    PlatformSTTDefaults,
    PlatformTTSCatalog,
    PlatformTTSDefaults,
)
from api.services.configuration.platform import catalog
from api.services.configuration.platform.catalog import (
    NumericRange,
    PlatformOption,
    PlatformPipelineMode,
)

_MODES = (
    PlatformModeOption(
        id=PlatformPipelineMode.REALTIME,
        label="Speech-to-Speech",
        description=(
            "One model listens and speaks directly. Most natural and lowest latency."
        ),
        recommended=True,
    ),
    PlatformModeOption(
        id=PlatformPipelineMode.PIPELINE,
        label="Speech-to-Text → LLM → Text-to-Speech",
        description=(
            "Separate transcriber, language model and voice. More voices and "
            "languages, and finer control over each step."
        ),
    ),
)


def build_platform_model_catalog(
    *,
    enabled: bool,
    llm_models: tuple[PlatformOption, ...] = catalog.LLM_MODELS,
    locked: bool = False,
) -> PlatformModelCatalog:
    """The catalog one organization sees.

    *llm_models* is what its policy offers; *locked* tells the UI that
    support pinned its settings.
    """
    return PlatformModelCatalog(
        enabled=enabled,
        locked=locked,
        default_mode=catalog.DEFAULT_PIPELINE_MODE,
        modes=list(_MODES),
        realtime=PlatformRealtimeCatalog(
            models=options_for(catalog.REALTIME_MODELS),
            voices=options_for(catalog.REALTIME_VOICES),
            languages=list(catalog.REALTIME_LANGUAGES),
            defaults=PlatformRealtimeDefaults(
                model=catalog.DEFAULT_REALTIME_MODEL,
                voice=catalog.DEFAULT_REALTIME_VOICE,
                language=catalog.DEFAULT_REALTIME_LANGUAGE,
            ),
        ),
        pipeline=PlatformPipelineCatalog(
            llm=PlatformLLMCatalog(
                models=options_for(llm_models),
                temperature_range=_range(catalog.LLM_TEMPERATURE_RANGE),
                defaults=PlatformLLMDefaults(
                    model=catalog.DEFAULT_LLM_MODEL,
                    temperature=catalog.DEFAULT_LLM_TEMPERATURE,
                ),
            ),
            stt=PlatformSTTCatalog(
                models=options_for(catalog.STT_MODELS),
                languages=list(catalog.STT_LANGUAGES),
                defaults=PlatformSTTDefaults(
                    model=catalog.DEFAULT_STT_MODEL,
                    language=catalog.DEFAULT_STT_LANGUAGE,
                ),
            ),
            tts=PlatformTTSCatalog(
                models=options_for(catalog.TTS_MODELS),
                languages=list(catalog.TTS_LANGUAGES),
                speed_range=_range(catalog.TTS_SPEED_RANGE),
                voice_catalog=catalog.TTS_VOICE_CATALOG,
                defaults=PlatformTTSDefaults(
                    model=catalog.DEFAULT_TTS_MODEL,
                    voice=catalog.DEFAULT_TTS_VOICE,
                    language=catalog.DEFAULT_TTS_LANGUAGE,
                    speed=catalog.DEFAULT_TTS_SPEED,
                ),
            ),
        ),
    )


def options_for(options: tuple[PlatformOption, ...]) -> list[PlatformCatalogOption]:
    return [
        PlatformCatalogOption(
            id=option.id,
            label=option.label,
            description=option.description,
            recommended=option.recommended,
            gender=option.gender,
            preview_url=option.preview_url,
            languages=list(option.languages) if option.languages else None,
        )
        for option in options
    ]


def _range(value: NumericRange) -> PlatformCatalogRange:
    return PlatformCatalogRange(min=value.min, max=value.max, step=value.step)
