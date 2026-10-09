"""Turn platform choices into the Google service configs the runtime builds."""

from __future__ import annotations

from dataclasses import dataclass

from api.schemas.platform_models import (
    PlatformAIModelConfiguration,
    PlatformLLMChoice,
)
from api.services.configuration.platform.catalog import PlatformPipelineMode
from api.services.configuration.platform.settings import PlatformVertexSettings
from api.services.configuration.registry import (
    GoogleSTTConfiguration,
    GoogleTTSConfiguration,
    GoogleVertexLLMConfiguration,
    GoogleVertexRealtimeLLMConfiguration,
    ServiceProviders,
)


@dataclass(frozen=True, slots=True)
class PlatformServices:
    llm: GoogleVertexLLMConfiguration
    realtime: GoogleVertexRealtimeLLMConfiguration | None = None
    stt: GoogleSTTConfiguration | None = None
    tts: GoogleTTSConfiguration | None = None

    @property
    def is_realtime(self) -> bool:
        return self.realtime is not None


def compile_platform_services(
    configuration: PlatformAIModelConfiguration,
    settings: PlatformVertexSettings,
) -> PlatformServices:
    if configuration.pipeline_mode is PlatformPipelineMode.REALTIME:
        realtime = configuration.realtime
        if realtime is None:
            raise ValueError("platform.realtime is required")
        return PlatformServices(
            realtime=GoogleVertexRealtimeLLMConfiguration(
                provider=ServiceProviders.GOOGLE_VERTEX_REALTIME,
                model=realtime.model,
                voice=realtime.voice,
                language=realtime.language,
                project_id=settings.project_id,
                location=settings.realtime_location,
                credentials=settings.credentials_json,
            ),
            # Realtime calls still need a text model for variable extraction,
            # QA and other post-call work.
            llm=_vertex_llm(
                configuration.pipeline.llm
                if configuration.pipeline is not None
                else PlatformLLMChoice(),
                settings,
            ),
        )

    pipeline = configuration.pipeline
    if pipeline is None:
        raise ValueError("platform.pipeline is required")
    return PlatformServices(
        llm=_vertex_llm(pipeline.llm, settings),
        stt=GoogleSTTConfiguration(
            provider=ServiceProviders.GOOGLE,
            model=pipeline.stt.model,
            language=pipeline.stt.language,
            location=settings.speech_location,
            credentials=settings.credentials_json,
        ),
        tts=GoogleTTSConfiguration(
            provider=ServiceProviders.GOOGLE,
            model=pipeline.tts.model,
            voice=pipeline.tts.voice,
            language=pipeline.tts.language,
            speed=pipeline.tts.speed,
            location=settings.speech_location,
            credentials=settings.credentials_json,
        ),
    )


def _vertex_llm(
    choice: PlatformLLMChoice, settings: PlatformVertexSettings
) -> GoogleVertexLLMConfiguration:
    return GoogleVertexLLMConfiguration(
        provider=ServiceProviders.GOOGLE_VERTEX,
        model=choice.model,
        temperature=choice.temperature,
        project_id=settings.project_id,
        location=settings.llm_location,
        credentials=settings.credentials_json,
    )
