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

export interface PlatformFormStateResult {
    state: PlatformFormState;
    // The stored configuration wasn't a platform one, so the form starts from
    // the catalog defaults (keeping its language where the catalog offers it).
    migratedFrom: "dograh" | "byok" | "empty" | null;
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
export function platformFormStateFromConfiguration(
    configuration: unknown,
    catalog: PlatformModelCatalog,
): PlatformFormStateResult {
    const defaults = defaultPlatformFormState(catalog);
    const stored = record(configuration);
    if (stored.mode !== "platform") {
        const mode = stored.mode === "dograh" || stored.mode === "byok" ? stored.mode : "empty";
        return { state: carryOverLanguage(stored, defaults, catalog), migratedFrom: mode };
    }

    const platform = record(stored.platform);
    const realtime = record(platform.realtime);
    const pipeline = record(platform.pipeline);
    const llm = record(pipeline.llm);
    const stt = record(pipeline.stt);
    const tts = record(pipeline.tts);

    return {
        migratedFrom: null,
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
                    llm.temperature === null || typeof llm.temperature === "number"
                        ? (llm.temperature as number | null)
                        : defaults.llm.temperature,
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

/** Keep a Dograh-managed or BYOK configuration's language where the catalog has it. */
function carryOverLanguage(
    stored: Record<string, unknown>,
    defaults: PlatformFormState,
    catalog: PlatformModelCatalog,
): PlatformFormState {
    const byok = record(stored.byok);
    const realtimeService = record(record(byok.realtime).realtime);
    const pipeline = record(byok.pipeline);
    const candidates = [
        record(stored.dograh).language,
        realtimeService.language,
        record(pipeline.stt).language,
    ].filter((value): value is string => typeof value === "string" && value.length > 0);

    const state: PlatformFormState = {
        ...defaults,
        realtime: { ...defaults.realtime },
        stt: { ...defaults.stt },
    };
    for (const language of candidates) {
        const base = language.split("-")[0].toLowerCase();
        if (catalog.realtime.languages.includes(base)) {
            state.realtime.language = base;
            break;
        }
    }
    const sttLanguages = sttLanguagesFor(catalog, state.stt.model);
    const sttLanguage = candidates.find((language) => sttLanguages.includes(language));
    if (sttLanguage) state.stt.language = sttLanguage;
    if (
        typeof realtimeService.voice === "string"
        && catalog.realtime.voices.some((voice) => voice.id === realtimeService.voice)
    ) {
        state.realtime.voice = realtimeService.voice;
    }
    return state;
}

/**
 * The wire configuration for *state*. Only the active mode's block is sent:
 * the server validates every block it receives, and the inactive one isn't
 * on screen to be corrected.
 */
export function buildPlatformConfiguration(
    state: PlatformFormState,
): OrganizationAiModelConfigurationV2 {
    return {
        version: 2,
        mode: "platform",
        platform:
            state.pipelineMode === "realtime"
                ? { pipeline_mode: "realtime", realtime: { ...state.realtime } }
                : {
                    pipeline_mode: "pipeline",
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

/** Whether *voice* is one of TTS *model*'s voices speaking *language*. */
export function isVoiceFor(
    catalog: PlatformModelCatalog,
    model: string,
    language: string,
    voice: string,
): boolean {
    const family = catalog.pipeline.tts.models.find((item) => item.id === model)?.voice_family;
    const prefix = family ? `${language}-${family}-` : `${language}-`;
    return voice.startsWith(prefix) && /^[A-Za-z]+$/.test(voice.slice(prefix.length));
}

/**
 * The same voice persona in another language, where the model has it
 * ("en-US-Chirp3-HD-Kore" → "en-GB-Chirp3-HD-Kore"); otherwise "" so the
 * customer picks a voice for that language.
 */
export function voiceInLanguage(
    catalog: PlatformModelCatalog,
    model: string,
    voice: string,
    language: string,
): string {
    const family = catalog.pipeline.tts.models.find((item) => item.id === model)?.voice_family;
    const name = voice.split("-").pop() ?? "";
    const translated = family ? `${language}-${family}-${name}` : voice;
    return isVoiceFor(catalog, model, language, translated) ? translated : "";
}

/**
 * The language to keep when the speech-to-text model changes: the same one if
 * the model serves it, else the same base language, else the model's default.
 */
export function sttLanguageForModel(
    catalog: PlatformModelCatalog,
    model: string,
    language: string,
): string {
    const served = sttLanguagesFor(catalog, model);
    if (served.includes(language)) return language;
    const base = language.split("-")[0];
    const sibling = served.find((code) => code.split("-")[0] === base);
    if (sibling) return sibling;
    const fallback = catalog.pipeline.stt.defaults.language;
    return served.includes(fallback) ? fallback : (served[0] ?? fallback);
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
    if (!tts.languages.includes(state.tts.language)) errors.push("Choose a voice language.");
    if (!isVoiceFor(catalog, state.tts.model, state.tts.language, state.tts.voice)) {
        errors.push("Choose a voice that speaks the selected voice language.");
    }
    if (state.tts.speed < tts.speed_range.min || state.tts.speed > tts.speed_range.max) {
        errors.push(`Speed must be between ${tts.speed_range.min} and ${tts.speed_range.max}.`);
    }
    return errors;
}

let displayNames: Intl.DisplayNames | null | undefined;

/** Display name for a BCP-47 code, e.g. "en-GB" → "British English". */
export function languageLabel(code: string): string {
    if (displayNames === undefined) {
        try {
            displayNames = new Intl.DisplayNames(["en"], { type: "language" });
        } catch {
            displayNames = null;
        }
    }
    try {
        const name = displayNames?.of(code);
        if (name && name !== code) return name;
    } catch {
        // Not a code Intl understands; fall through.
    }
    return LANGUAGE_DISPLAY_NAMES[code] || code;
}
