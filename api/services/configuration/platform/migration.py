"""Map an existing model configuration onto platform choices.

Used by the one-off org migration: an organization on the Dograh-managed
service or on its own keys moves to platform models, keeping its voice,
language and models wherever the platform offers an equivalent. Anything that
does not map falls back to the platform default, and every fallback is noted so
the operator can see what changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from api.schemas.ai_model_configuration import OrganizationAIModelConfigurationV2
from api.schemas.platform_models import (
    PlatformAIModelConfiguration,
    PlatformLLMChoice,
    PlatformPipelineChoice,
    PlatformRealtimeChoice,
    PlatformSTTChoice,
    PlatformTTSChoice,
)
from api.services.configuration.platform import catalog
from api.services.configuration.platform.catalog import PlatformPipelineMode
from api.services.configuration.registry import ServiceProviders

_REALTIME_PROVIDERS = frozenset(
    {
        ServiceProviders.GOOGLE_VERTEX_REALTIME.value,
        ServiceProviders.GOOGLE_REALTIME.value,
    }
)


@dataclass(slots=True)
class PlatformMigration:
    configuration: PlatformAIModelConfiguration
    notes: list[str] = field(default_factory=list)


def migrate_to_platform(
    existing: OrganizationAIModelConfigurationV2 | None,
) -> PlatformMigration:
    """Return the platform configuration that best matches *existing*."""
    if existing is None:
        return PlatformMigration(
            _realtime(PlatformRealtimeChoice()), ["no configuration; using default"]
        )
    if existing.mode == "platform" and existing.platform is not None:
        return PlatformMigration(existing.platform)
    if existing.mode == "dograh" and existing.dograh is not None:
        return _from_dograh(
            language=existing.dograh.language,
            temperature=existing.dograh.temperature,
        )
    if existing.byok is not None:
        if existing.byok.mode == "realtime" and existing.byok.realtime is not None:
            return _from_byok_realtime(
                existing.byok.realtime.realtime, existing.byok.realtime.llm
            )
        if existing.byok.pipeline is not None:
            pipeline = existing.byok.pipeline
            return _from_byok_pipeline(pipeline.llm, pipeline.stt, pipeline.tts)
    return PlatformMigration(
        _realtime(PlatformRealtimeChoice()), ["unrecognised configuration"]
    )


def _from_dograh(*, language: str, temperature: float | None) -> PlatformMigration:
    notes = ["Fallcha.ai managed voice replaced by Gemini Live voice Charon"]
    realtime = PlatformRealtimeChoice(language=_realtime_language(language, notes))
    llm = _llm_choice(catalog.DEFAULT_LLM_MODEL, temperature, notes)
    return PlatformMigration(
        PlatformAIModelConfiguration(
            pipeline_mode=PlatformPipelineMode.REALTIME,
            realtime=realtime,
            pipeline=PlatformPipelineChoice(llm=llm),
        ),
        notes,
    )


def _from_byok_realtime(realtime: Any, llm: Any) -> PlatformMigration:
    notes: list[str] = []
    voice = catalog.DEFAULT_REALTIME_VOICE
    language = catalog.DEFAULT_REALTIME_LANGUAGE
    if getattr(realtime, "provider", None) in _REALTIME_PROVIDERS:
        voice = _allowed(
            getattr(realtime, "voice", None),
            catalog.option_ids(catalog.REALTIME_VOICES),
            catalog.DEFAULT_REALTIME_VOICE,
            "realtime voice",
            notes,
        )
        language = _realtime_language(getattr(realtime, "language", None), notes)
    else:
        notes.append(
            f"realtime provider {getattr(realtime, 'provider', None)!r} replaced by "
            "Gemini Live"
        )
    return PlatformMigration(
        PlatformAIModelConfiguration(
            pipeline_mode=PlatformPipelineMode.REALTIME,
            realtime=PlatformRealtimeChoice(voice=voice, language=language),
            pipeline=PlatformPipelineChoice(llm=_llm_from_service(llm, notes)),
        ),
        notes,
    )


def _from_byok_pipeline(llm: Any, stt: Any, tts: Any) -> PlatformMigration:
    notes: list[str] = []
    llm_choice = _llm_from_service(llm, notes)

    tts_choice = _tts_from_service(tts)
    stt_choice = _stt_from_service(
        stt,
        # What callers speak: the transcriber's language first, then the
        # voice's locale.
        [getattr(stt, "language", None), tts_choice.language if tts_choice else None],
        notes,
    )
    if tts_choice is None:
        # Without a Google voice to keep, a pipeline would change voice anyway;
        # Gemini Live is the better default for that caller.
        notes.append(
            f"text-to-speech voice {getattr(tts, 'voice', None)!r} has no platform "
            "equivalent; switched to Gemini Live"
        )
        return PlatformMigration(
            PlatformAIModelConfiguration(
                pipeline_mode=PlatformPipelineMode.REALTIME,
                realtime=PlatformRealtimeChoice(
                    language=_realtime_language(
                        getattr(stt, "language", None) or stt_choice.language, notes
                    )
                ),
                pipeline=PlatformPipelineChoice(llm=llm_choice, stt=stt_choice),
            ),
            notes,
        )

    return PlatformMigration(
        PlatformAIModelConfiguration(
            pipeline_mode=PlatformPipelineMode.PIPELINE,
            pipeline=PlatformPipelineChoice(
                llm=llm_choice, stt=stt_choice, tts=tts_choice
            ),
        ),
        notes,
    )


def _stt_from_service(
    stt: Any, languages: list[str | None], notes: list[str]
) -> PlatformSTTChoice:
    model = catalog.DEFAULT_STT_MODEL
    if getattr(stt, "provider", None) == ServiceProviders.GOOGLE.value:
        model = _allowed(
            getattr(stt, "model", None),
            catalog.option_ids(catalog.STT_MODELS),
            catalog.DEFAULT_STT_MODEL,
            "speech-to-text model",
            notes,
        )
    else:
        notes.append(
            f"speech-to-text provider {getattr(stt, 'provider', None)!r} replaced "
            f"by Google {model}"
        )
    other_models = [o.id for o in catalog.STT_MODELS if o.id != model]
    # The exact locale on any model beats a sibling locale on the same model.
    for language, exact in [(lang, ex) for lang in languages for ex in (True, False)]:
        for candidate_model in (model, *other_models):
            locale = _stt_locale(language, candidate_model, exact=exact)
            if locale is None:
                continue
            if candidate_model != model:
                notes.append(
                    f"speech-to-text model {model!r} does not serve {locale}; "
                    f"using {candidate_model!r}"
                )
            elif locale != language:
                notes.append(f"speech-to-text language {language!r} mapped to {locale}")
            return PlatformSTTChoice(model=candidate_model, language=locale)
    notes.append(
        f"speech-to-text language {languages[0]!r} replaced by "
        f"{catalog.DEFAULT_STT_LANGUAGE!r}"
    )
    return PlatformSTTChoice()


def _stt_locale(language: str | None, model: str, *, exact: bool) -> str | None:
    """The locale *model* serves for *language*: exact, or same base language."""
    if not language:
        return None
    served = catalog.stt_model_languages(model)
    if language in served:
        return language
    if exact:
        return None
    base = language.split("-")[0].lower()
    # Prefer the language's home locale (fr-FR, de-DE), and en-US for English.
    preferred = "en-US" if base == "en" else f"{base}-{base.upper()}"
    if preferred in served:
        return preferred
    same_base = sorted(code for code in served if code.split("-")[0].lower() == base)
    return same_base[0] if same_base else None


def _tts_from_service(tts: Any) -> PlatformTTSChoice | None:
    if getattr(tts, "provider", None) != ServiceProviders.GOOGLE.value:
        return None
    voice = getattr(tts, "voice", None)
    if not isinstance(voice, str):
        return None
    locale = catalog.tts_voice_locale(catalog.DEFAULT_TTS_MODEL, voice)
    if locale is None:
        return None
    speed = getattr(tts, "speed", catalog.DEFAULT_TTS_SPEED)
    try:
        return PlatformTTSChoice(voice=voice, language=locale, speed=speed)
    except ValidationError:
        return None


def _llm_from_service(llm: Any, notes: list[str]) -> PlatformLLMChoice:
    model = getattr(llm, "model", None)
    if getattr(llm, "provider", None) not in (
        ServiceProviders.GOOGLE_VERTEX.value,
        ServiceProviders.GOOGLE.value,
    ):
        notes.append(f"LLM {model!r} replaced by {catalog.DEFAULT_LLM_MODEL}")
        model = catalog.DEFAULT_LLM_MODEL
    return _llm_choice(model, getattr(llm, "temperature", None), notes)


def _llm_choice(
    model: str | None, temperature: float | None, notes: list[str]
) -> PlatformLLMChoice:
    model = _allowed(
        model,
        catalog.option_ids(catalog.LLM_MODELS),
        catalog.DEFAULT_LLM_MODEL,
        "LLM",
        notes,
    )
    if temperature is None:
        return PlatformLLMChoice(model=model)
    try:
        return PlatformLLMChoice(model=model, temperature=temperature)
    except ValidationError:
        notes.append(f"temperature {temperature!r} reset to the default")
        return PlatformLLMChoice(model=model)


def _realtime_language(language: str | None, notes: list[str]) -> str:
    """Gemini Live takes two-letter codes; reduce 'en-IE' to 'en'."""
    allowed = frozenset(catalog.REALTIME_LANGUAGES)
    base = (language or "").split("-")[0].lower()
    if base in allowed:
        return base
    if language:
        notes.append(
            f"language {language!r} replaced by {catalog.DEFAULT_REALTIME_LANGUAGE!r}"
        )
    return catalog.DEFAULT_REALTIME_LANGUAGE


def _allowed(
    value: str | None,
    allowed: frozenset[str],
    default: str,
    what: str,
    notes: list[str],
) -> str:
    if value is not None and value in allowed:
        return value
    notes.append(f"{what} {value!r} replaced by {default!r}")
    return default


def _realtime(choice: PlatformRealtimeChoice) -> PlatformAIModelConfiguration:
    return PlatformAIModelConfiguration(
        pipeline_mode=PlatformPipelineMode.REALTIME, realtime=choice
    )


_V2_OVERRIDE_KEY = "model_configuration_v2_override"


def migrate_workflow_configurations(
    workflow_configurations: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[str]] | None:
    """Move a workflow's model overrides onto platform choices.

    Returns the new configurations and notes, or None when nothing changes.
    A v2 override becomes its platform equivalent; a legacy provider overlay
    is dropped, since platform agents can only override through v2.
    """
    if not isinstance(workflow_configurations, dict):
        return None
    override = workflow_configurations.get(_V2_OVERRIDE_KEY)
    has_legacy = "model_overrides" in workflow_configurations
    if not override and not has_legacy:
        return None

    migrated = dict(workflow_configurations)
    notes: list[str] = []
    if has_legacy:
        migrated.pop("model_overrides")
        notes.append("legacy model_overrides removed")
    if override:
        try:
            existing: OrganizationAIModelConfigurationV2 | None = (
                OrganizationAIModelConfigurationV2.model_validate(override)
            )
        except ValidationError:
            existing = None
            notes.append("unparsable model override replaced by the default")
        if existing is None or existing.mode != "platform":
            result = migrate_to_platform(existing)
            migrated[_V2_OVERRIDE_KEY] = OrganizationAIModelConfigurationV2(
                mode="platform", platform=result.configuration
            ).model_dump(mode="json", exclude_none=True)
            notes.extend(result.notes)
    if migrated == workflow_configurations:
        return None
    return migrated, notes
