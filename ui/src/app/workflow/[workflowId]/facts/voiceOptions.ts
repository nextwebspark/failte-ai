// The voices "How it sounds" offers: the agent's own and a few others of the
// same kind (Gemini Live, or Chirp 3 HD in the same language), each with the
// Google voice that previews it. Pure; the catalog is the only source.

import type { OrganizationAiModelConfigurationV2, PlatformModelCatalog } from "@/client/types.gen";
import { buildPlatformConfiguration, platformFormStateFromConfiguration } from "@/lib/platformModelConfig";

/** How many other voices sit beside the agent's own. */
export const ALTERNATIVE_VOICES = 3;

export type VoiceOption = {
    /** What the configuration stores: "Kore", or "en-GB-Chirp3-HD-Kore". */
    value: string;
    /** The persona name, "Kore". */
    name: string;
    /** "Female", "Male" or null. */
    gender: string | null;
    /** Google's one-word style, "Firm". */
    style: string | null;
    /** The Google voice that reads the preview. */
    previewVoiceId: string;
};

export type VoiceChoices = {
    current: VoiceOption;
    alternatives: VoiceOption[];
};

const CHIRP_FAMILY = "Chirp3-HD";
// Gemini Live voices are previewed with the Chirp 3 HD voice of the same name
// (they share it); the catalog's own samples use this accent.
const LIVE_PREVIEW_LOCALE = "en-US";

function personaName(value: string): string {
    return value.split("-").pop() ?? value;
}

function option(value: string, previewVoiceId: string, catalog: PlatformModelCatalog): VoiceOption {
    const name = personaName(value);
    const persona = catalog.realtime.voices.find((voice) => voice.id === name);
    const gender = persona?.gender ?? null;
    return {
        value,
        name: persona?.label ?? name,
        gender: gender ? gender.charAt(0).toUpperCase() + gender.slice(1) : null,
        style: persona?.description ?? null,
        previewVoiceId,
    };
}

/** The locale a Gemini Live language is previewed in ("de" → "de-DE"). */
function liveLocale(language: string, catalog: PlatformModelCatalog): string {
    const base = language.split("-")[0].toLowerCase();
    if (base === "en") return LIVE_PREVIEW_LOCALE;
    return catalog.pipeline.tts.languages.find((code) => code.split("-")[0] === base) ?? LIVE_PREVIEW_LOCALE;
}

/**
 * Others first by the catalog's recommendation, then mixing genders so the
 * owner hears a real choice, never the agent's own voice twice.
 */
function pickAlternatives(currentName: string, catalog: PlatformModelCatalog, count: number): string[] {
    const voices = catalog.realtime.voices.filter((voice) => voice.id !== currentName);
    const ranked = [...voices.filter((v) => v.recommended), ...voices.filter((v) => !v.recommended)];
    const picked: string[] = [];
    const genders = new Set<string>();
    // The first two differ in gender where the catalog allows; the rest
    // follow the ranking.
    for (const voice of ranked) {
        if (picked.length >= Math.min(2, count)) break;
        const gender = voice.gender ?? "";
        if (genders.has(gender)) continue;
        picked.push(voice.id);
        genders.add(gender);
    }
    for (const voice of ranked) {
        if (picked.length >= count) break;
        if (!picked.includes(voice.id)) picked.push(voice.id);
    }
    return picked;
}

/**
 * The agent's voice and a few others it could switch to, or null when the
 * configuration isn't a platform one (nothing here can preview or change it).
 */
export function voiceChoices(
    configuration: unknown,
    catalog: PlatformModelCatalog,
    count = ALTERNATIVE_VOICES,
): VoiceChoices | null {
    const stored = configuration && typeof configuration === "object" ? (configuration as Record<string, unknown>) : {};
    if (stored.mode !== "platform") return null;
    const { state } = platformFormStateFromConfiguration(configuration, catalog);
    if (state.pipelineMode === "realtime") {
        const locale = liveLocale(state.realtime.language, catalog);
        const make = (name: string) => option(name, `${locale}-${CHIRP_FAMILY}-${name}`, catalog);
        return {
            current: make(state.realtime.voice),
            alternatives: pickAlternatives(state.realtime.voice, catalog, count).map(make),
        };
    }
    const family = catalog.pipeline.tts.models.find((model) => model.id === state.tts.model)?.voice_family;
    if (family !== CHIRP_FAMILY) return null;
    const language = state.tts.language;
    const make = (name: string) => {
        const value = `${language}-${family}-${name}`;
        return option(value, value, catalog);
    };
    const currentName = personaName(state.tts.voice);
    return {
        current: { ...make(currentName), value: state.tts.voice, previewVoiceId: state.tts.voice },
        alternatives: pickAlternatives(currentName, catalog, count).map(make),
    };
}

/** *configuration* (or the catalog defaults) speaking with *voice* instead. */
export function withVoice(
    configuration: unknown,
    catalog: PlatformModelCatalog,
    voice: string,
): OrganizationAiModelConfigurationV2 {
    const { state } = platformFormStateFromConfiguration(configuration, catalog);
    if (state.pipelineMode === "realtime") {
        return buildPlatformConfiguration({ ...state, realtime: { ...state.realtime, voice } });
    }
    return buildPlatformConfiguration({ ...state, tts: { ...state.tts, voice } });
}

/** The API path that reads the agent's greeting in *voice*. */
export function voicePreviewPath(workflowId: number, previewVoiceId: string): string {
    return `/api/v1/workflow/${workflowId}/voice-preview?voice_id=${encodeURIComponent(previewVoiceId)}`;
}
