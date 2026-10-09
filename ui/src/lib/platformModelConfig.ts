// Form state and wire mapping for platform-managed models: the customer picks
// a mode and, for that mode, models, voice and language from the server's
// catalog (GET /organizations/model-configurations/v2/defaults → `platform`).
// Nothing here knows which models exist; the catalog is the only source.

import type {
    OrganizationAiModelConfigurationV2,
    PlatformCatalogOption,
    PlatformModelCatalog,
    PlatformPipelineMode,
} from "@/client/types.gen";
import { LANGUAGE_DISPLAY_NAMES } from "@/constants/languages";

export interface PlatformFormState {
    pipelineMode: PlatformPipelineMode;
    realtime: { model: string; voice: string; language: string };
    llm: { model: string; temperature: number | null };
    stt: { model: string; language: string };
    tts: { model: string; voice: string; language: string; speed: number };
}

export interface ParsedPlatformConfiguration {
    state: PlatformFormState;
    // The stored configuration wasn't a platform one (Dograh-managed, BYOK or
    // none), so the form starts from the catalog defaults.
    replacedMode: "dograh" | "byok" | "empty" | null;
}

export function defaultPlatformFormState(catalog: PlatformModelCatalog): PlatformFormState {
    const { realtime, pipeline } = catalog;
    return {
        pipelineMode: catalog.default_mode,
        realtime: { ...realtime.defaults },
        llm: {
            model: pipeline.llm.defaults.model,
            temperature: pipeline.llm.defaults.temperature ?? null,
        },
        stt: { ...pipeline.stt.defaults },
        tts: { ...pipeline.tts.defaults },
    };
}

function record(value: unknown): Record<string, unknown> {
    return value && typeof value === "object" && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : {};
}

function stringOr(value: unknown, fallback: string): string {
    return typeof value === "string" && value.length > 0 ? value : fallback;
}

function numberOr(value: unknown, fallback: number): number {
    return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

/** Read a stored configuration into form state, filling gaps from the catalog. */
export function parsePlatformConfiguration(
    configuration: unknown,
    catalog: PlatformModelCatalog,
): ParsedPlatformConfiguration {
    const defaults = defaultPlatformFormState(catalog);
    const stored = record(configuration);
    if (stored.mode !== "platform") {
        const mode = stored.mode;
        return {
            state: defaults,
            replacedMode: mode === "dograh" || mode === "byok" ? mode : "empty",
        };
    }

    const platform = record(stored.platform);
    const realtime = record(platform.realtime);
    const pipeline = record(platform.pipeline);
    const llm = record(pipeline.llm);
    const stt = record(pipeline.stt);
    const tts = record(pipeline.tts);
    const temperature = llm.temperature;

    return {
        replacedMode: null,
        state: {
            pipelineMode: platform.pipeline_mode === "pipeline" ? "pipeline" : "realtime",
            realtime: {
                model: stringOr(realtime.model, defaults.realtime.model),
                voice: stringOr(realtime.voice, defaults.realtime.voice),
                language: stringOr(realtime.language, defaults.realtime.language),
            },
            llm: {
                model: stringOr(llm.model, defaults.llm.model),
                temperature:
                    temperature === null
                        ? null
                        : numberOr(temperature, defaults.llm.temperature ?? 0),
            },
            stt: {
                model: stringOr(stt.model, defaults.stt.model),
                language: stringOr(stt.language, defaults.stt.language),
            },
            tts: {
                model: stringOr(tts.model, defaults.tts.model),
                voice: stringOr(tts.voice, defaults.tts.voice),
                language: stringOr(tts.language, defaults.tts.language),
                speed: numberOr(tts.speed, defaults.tts.speed),
            },
        },
    };
}

/**
 * The wire configuration for *state*. Both blocks are sent so switching modes
 * back and forth keeps the other mode's choices; in realtime mode the pipeline
 * LLM is the model used for post-call work.
 */
export function buildPlatformConfiguration(
    state: PlatformFormState,
): OrganizationAiModelConfigurationV2 {
    return {
        version: 2,
        mode: "platform",
        platform: {
            pipeline_mode: state.pipelineMode,
            realtime: { ...state.realtime },
            pipeline: {
                llm: { ...state.llm },
                stt: { ...state.stt },
                tts: { ...state.tts },
            },
        },
    };
}

export function sttLanguagesFor(catalog: PlatformModelCatalog, model: string): string[] {
    const option = catalog.pipeline.stt.models.find((item) => item.id === model);
    return option?.languages ?? catalog.pipeline.stt.languages;
}

/** The locale encoded in a Google voice name, e.g. "en-GB-Chirp3-HD-Kore" → "en-GB". */
export function voiceLocale(voice: string): string | null {
    const match = /^([a-z]{2,3}-[A-Z]{2})-/.exec(voice);
    return match ? match[1] : null;
}

/** Human-readable problems with *state*; empty when it can be saved. */
export function validatePlatformFormState(
    state: PlatformFormState,
    catalog: PlatformModelCatalog,
): string[] {
    const errors: string[] = [];
    const ids = (options: PlatformCatalogOption[]) => options.map((option) => option.id);

    if (state.pipelineMode === "realtime") {
        const { realtime } = catalog;
        if (!ids(realtime.models).includes(state.realtime.model)) errors.push("Choose a model.");
        if (!ids(realtime.voices).includes(state.realtime.voice)) errors.push("Choose a voice.");
        if (!realtime.languages.includes(state.realtime.language)) errors.push("Choose a language.");
        return errors;
    }

    const { llm, stt, tts } = catalog.pipeline;
    if (!ids(llm.models).includes(state.llm.model)) errors.push("Choose a language model.");
    if (
        state.llm.temperature !== null
        && (state.llm.temperature < llm.temperature_range.min
            || state.llm.temperature > llm.temperature_range.max)
    ) {
        errors.push(
            `Temperature must be between ${llm.temperature_range.min} and ${llm.temperature_range.max}.`,
        );
    }
    if (!ids(stt.models).includes(state.stt.model)) errors.push("Choose a speech-to-text model.");
    if (!sttLanguagesFor(catalog, state.stt.model).includes(state.stt.language)) {
        errors.push("The speech-to-text model doesn't support this language. Pick another language or model.");
    }
    if (!ids(tts.models).includes(state.tts.model)) errors.push("Choose a text-to-speech model.");
    if (voiceLocale(state.tts.voice) !== state.tts.language) {
        errors.push("Choose a voice that speaks the selected text-to-speech language.");
    }
    if (state.tts.speed < tts.speed_range.min || state.tts.speed > tts.speed_range.max) {
        errors.push(`Speed must be between ${tts.speed_range.min} and ${tts.speed_range.max}.`);
    }
    return errors;
}

let displayNames: Intl.DisplayNames | null | undefined;

/** Display name for a BCP-47 code, e.g. "en-GB" → "British English". */
export function languageLabel(code: string): string {
    if (LANGUAGE_DISPLAY_NAMES[code]) return LANGUAGE_DISPLAY_NAMES[code];
    if (displayNames === undefined) {
        try {
            displayNames = new Intl.DisplayNames(["en"], { type: "language" });
        } catch {
            displayNames = null;
        }
    }
    try {
        return displayNames?.of(code) ?? code;
    } catch {
        return code;
    }
}
