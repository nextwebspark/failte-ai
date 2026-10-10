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

/**
 * Read a stored configuration into form state, filling gaps from the catalog.
 *
 * Only the active mode's block is stored, so the other mode starts from
 * *fallback* (the workspace configuration, for an agent) when that sets it,
 * and otherwise from this configuration's own mode: flipping between modes
 * keeps the language and voice instead of resetting them to the defaults.
 */
export function platformFormStateFromConfiguration(
    configuration: unknown,
    catalog: PlatformModelCatalog,
    fallback?: unknown,
): PlatformFormStateResult {
    const defaults = defaultPlatformFormState(catalog);
    const stored = record(configuration);
    if (stored.mode !== "platform") {
        const mode = stored.mode === "dograh" || stored.mode === "byok" ? stored.mode : "empty";
        return { state: carryOverLegacy(stored, defaults, catalog), migratedFrom: mode };
    }

    const platform = record(stored.platform);
    const realtime = record(platform.realtime);
    const pipeline = record(platform.pipeline);
    const llm = record(pipeline.llm);
    const stt = record(pipeline.stt);
    const tts = record(pipeline.tts);

    const state: PlatformFormState = {
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
    };

    const fallbackBlocks = fallback === undefined || fallback === configuration
        ? {}
        : storedBlocks(fallback, catalog);
    // The agent keeps its language and voice persona. The workspace setting
    // for that mode is used when it speaks the same language, since it has
    // the regional variant (en-GB rather than en-US) and models.
    if (Object.keys(realtime).length === 0) {
        const derived = realtimeFromPipeline(state, defaults, catalog);
        const workspace = fallbackBlocks.realtime;
        const persona = state.tts.voice.split("-").pop() ?? "";
        state.realtime = workspace && workspace.language === derived.language
            ? {
                ...workspace,
                voice: catalog.realtime.voices.some((voice) => voice.id === persona) ? persona : workspace.voice,
            }
            : derived;
    }
    if (Object.keys(pipeline).length === 0) {
        const workspace = fallbackBlocks.pipeline;
        const blocks = workspace && workspace.tts.language.split("-")[0] === state.realtime.language
            ? workspace
            : pipelineFromRealtime(state.realtime, defaults, catalog);
        const persona = voiceInLanguage(catalog, blocks.tts.model, state.realtime.voice, blocks.tts.language);
        Object.assign(state, {
            ...blocks,
            tts: { ...blocks.tts, voice: persona || blocks.tts.voice },
        });
    }
    return { migratedFrom: null, state };
}

type PipelineBlocks = Pick<PlatformFormState, "llm" | "stt" | "tts">;

/** The mode blocks *configuration* actually sets, read as form state. */
function storedBlocks(
    configuration: unknown,
    catalog: PlatformModelCatalog,
): { realtime?: PlatformFormState["realtime"]; pipeline?: PipelineBlocks } {
    const stored = record(configuration);
    let hasRealtime = false;
    let hasPipeline = false;
    if (stored.mode === "platform") {
        const platform = record(stored.platform);
        hasRealtime = Object.keys(record(platform.realtime)).length > 0;
        hasPipeline = Object.keys(record(platform.pipeline)).length > 0;
    } else if (stored.mode === "byok") {
        const byok = record(stored.byok);
        hasRealtime = byok.mode === "realtime";
        hasPipeline = byok.mode === "pipeline";
    }
    if (!hasRealtime && !hasPipeline) return {};
    const { state } = platformFormStateFromConfiguration(configuration, catalog);
    return {
        ...(hasRealtime ? { realtime: state.realtime } : {}),
        ...(hasPipeline ? { pipeline: { llm: state.llm, stt: state.stt, tts: state.tts } } : {}),
    };
}

/** Speech-to-speech choices matching a pipeline's voice persona and language. */
function realtimeFromPipeline(
    state: PlatformFormState,
    defaults: PlatformFormState,
    catalog: PlatformModelCatalog,
): PlatformFormState["realtime"] {
    const base = state.tts.language.split("-")[0].toLowerCase();
    const persona = state.tts.voice.split("-").pop() ?? "";
    return {
        model: defaults.realtime.model,
        voice: catalog.realtime.voices.some((voice) => voice.id === persona) ? persona : defaults.realtime.voice,
        language: catalog.realtime.languages.includes(base) ? base : defaults.realtime.language,
    };
}

/** Pipeline choices speaking a speech-to-speech setup's language with its voice persona. */
function pipelineFromRealtime(
    realtime: PlatformFormState["realtime"],
    defaults: PlatformFormState,
    catalog: PlatformModelCatalog,
): PipelineBlocks {
    const base = realtime.language;
    const ttsLanguage = defaults.tts.language.split("-")[0] === base
        ? defaults.tts.language
        : (catalog.pipeline.tts.languages.find((code) => code.split("-")[0] === base) ?? defaults.tts.language);
    const model = defaults.tts.model;
    const voice = voiceInLanguage(catalog, model, realtime.voice, ttsLanguage)
        || voiceInLanguage(catalog, model, defaults.tts.voice, ttsLanguage)
        || defaults.tts.voice;
    return {
        llm: { ...defaults.llm },
        stt: { model: defaults.stt.model, language: sttLanguageForModel(catalog, defaults.stt.model, ttsLanguage) },
        tts: { ...defaults.tts, voice, language: ttsLanguage },
    };
}

/**
 * Start a Dograh-managed or BYOK configuration's form from what it runs today:
 * its mode, and the models, voice and language the catalog also offers.
 */
function carryOverLegacy(
    stored: Record<string, unknown>,
    defaults: PlatformFormState,
    catalog: PlatformModelCatalog,
): PlatformFormState {
    const byok = record(stored.byok);
    const realtimeService = record(record(byok.realtime).realtime);
    const pipeline = record(byok.pipeline);
    const llm = record(pipeline.llm);
    const stt = record(pipeline.stt);
    const tts = record(pipeline.tts);
    const ids = (options: PlatformCatalogOption[]) => options.map((option) => option.id);

    const state: PlatformFormState = {
        ...defaults,
        pipelineMode: byok.mode === "pipeline" || byok.mode === "realtime" ? byok.mode : defaults.pipelineMode,
        realtime: { ...defaults.realtime },
        llm: { ...defaults.llm },
        stt: { ...defaults.stt },
        tts: { ...defaults.tts },
    };

    const candidates = [
        record(stored.dograh).language,
        realtimeService.language,
        stt.language,
        tts.language,
    ].filter((value): value is string => typeof value === "string" && value.length > 0);
    for (const language of candidates) {
        const base = language.split("-")[0].toLowerCase();
        if (catalog.realtime.languages.includes(base)) {
            state.realtime.language = base;
            break;
        }
    }
    if (typeof realtimeService.voice === "string" && ids(catalog.realtime.voices).includes(realtimeService.voice)) {
        state.realtime.voice = realtimeService.voice;
    }
    // Gemini API ids have no "google/" prefix; the catalog's Vertex ids do.
    const realtimeModel = [realtimeService.model, `google/${String(realtimeService.model)}`].find(
        (id): id is string => typeof id === "string" && ids(catalog.realtime.models).includes(id),
    );
    if (realtimeModel) state.realtime.model = realtimeModel;

    if (typeof llm.model === "string" && ids(catalog.pipeline.llm.models).includes(llm.model)) {
        state.llm.model = llm.model;
    }
    if (typeof stt.model === "string" && ids(catalog.pipeline.stt.models).includes(stt.model)) {
        state.stt.model = stt.model;
    }
    const sttLanguages = sttLanguagesFor(catalog, state.stt.model);
    const sttLanguage = candidates.find((language) => sttLanguages.includes(language));
    if (sttLanguage) state.stt.language = sttLanguage;

    const ttsLanguage = [tts.language, sttLanguage].find(
        (language): language is string =>
            typeof language === "string" && catalog.pipeline.tts.languages.includes(language),
    );
    if (ttsLanguage) {
        const voice = typeof tts.voice === "string" && isVoiceFor(catalog, state.tts.model, ttsLanguage, tts.voice)
            ? tts.voice
            : voiceInLanguage(catalog, state.tts.model, typeof tts.voice === "string" ? tts.voice : state.tts.voice, ttsLanguage)
              || voiceInLanguage(catalog, state.tts.model, state.tts.voice, ttsLanguage);
        state.tts = { ...state.tts, language: ttsLanguage, voice };
    }
    const { min, max } = catalog.pipeline.tts.speed_range;
    if (typeof tts.speed === "number" && tts.speed >= min && tts.speed <= max) state.tts.speed = tts.speed;

    // Only one mode was set up; the other follows its voice and language.
    if (byok.mode === "realtime") {
        Object.assign(state, pipelineFromRealtime(state.realtime, defaults, catalog));
    }
    if (byok.mode === "pipeline") state.realtime = realtimeFromPipeline(state, defaults, catalog);
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

/**
 * Where an agent's override editor starts: the override it has, platform or
 * an older provider one (read for its mode, voice and language), otherwise
 * the workspace configuration.
 */
export function platformOverrideSeed(savedOverride: unknown, workspaceConfiguration: unknown): unknown {
    const mode = record(savedOverride).mode;
    return mode === "platform" || mode === "byok" || mode === "dograh" ? savedOverride : workspaceConfiguration;
}

/** Whether *configuration* is an override from before platform models. */
export function isLegacyConfiguration(configuration: unknown): boolean {
    const mode = record(configuration).mode;
    return mode === "byok" || mode === "dograh";
}

/** One line describing a configuration, e.g. "Speech-to-Speech · Gemini Live 2.5 Flash · Charon · English". */
export function describePlatformConfiguration(configuration: unknown, catalog: PlatformModelCatalog): string {
    const stored = record(configuration);
    if (stored.mode !== "platform") return describeLegacyConfiguration(stored, catalog);
    const { state } = platformFormStateFromConfiguration(configuration, catalog);
    const label = (options: PlatformCatalogOption[], id: string) =>
        options.find((option) => option.id === id)?.label ?? id;
    const mode = label(catalog.modes, state.pipelineMode);
    if (state.pipelineMode === "realtime") {
        return [
            mode,
            label(catalog.realtime.models, state.realtime.model),
            label(catalog.realtime.voices, state.realtime.voice),
            languageLabel(state.realtime.language),
        ].join(" · ");
    }
    return [
        mode,
        label(catalog.pipeline.llm.models, state.llm.model),
        state.tts.voice.split("-").pop() ?? state.tts.voice,
        languageLabel(state.tts.language),
    ].join(" · ");
}

/** What a configuration from before platform models runs, described in one line. */
function describeLegacyConfiguration(stored: Record<string, unknown>, catalog: PlatformModelCatalog): string {
    if (stored.mode === "dograh") return "Older hosted setup";
    if (stored.mode !== "byok") return "Not set up yet";
    const byok = record(stored.byok);
    const label = (options: PlatformCatalogOption[], id: unknown) =>
        typeof id === "string" ? (options.find((option) => option.id === id)?.label ?? id) : null;
    const mode = typeof byok.mode === "string" ? label(catalog.modes, byok.mode) : null;
    let parts: (string | null)[];
    if (byok.mode === "realtime") {
        const realtime = record(record(byok.realtime).realtime);
        parts = [
            mode,
            label(catalog.realtime.models, realtime.model),
            typeof realtime.voice === "string" ? realtime.voice : null,
            typeof realtime.language === "string" ? languageLabel(realtime.language) : null,
        ];
    } else {
        const pipeline = record(byok.pipeline);
        const tts = record(pipeline.tts);
        const language = tts.language ?? record(pipeline.stt).language;
        parts = [
            mode,
            label(catalog.pipeline.llm.models, record(pipeline.llm).model),
            typeof tts.voice === "string" ? (tts.voice.split("-").pop() ?? tts.voice) : null,
            typeof language === "string" ? languageLabel(language) : null,
        ];
    }
    const summary = parts.filter(Boolean).join(" · ");
    return summary ? `${summary} (older provider setup)` : "Older provider setup";
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
