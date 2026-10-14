// What a saved model configuration runs, broken into the parts the "Current
// setup" card shows: the mode, the models and the voice with its persona
// (gender, Google's style word, our tone group, accent).

import type { PlatformCatalogOption, PlatformModelCatalog } from "@/client/types.gen";
import {
    describePlatformConfiguration,
    languageLabel,
    platformFormStateFromConfiguration,
} from "@/lib/platformModelConfig";
import { accentLabel, localesByLanguage, VOICE_TONES, voiceTone } from "@/lib/voiceFilters";

export interface VoiceSummary {
    name: string;
    gender: string | null;
    style: string | null;
    tone: string | null;
    recommended: boolean;
}

export type ConfigurationSummary =
    | {
        kind: "realtime";
        mode: string;
        model: string;
        language: string;
        voice: VoiceSummary;
    }
    | {
        kind: "pipeline";
        mode: string;
        stt: { model: string; language: string };
        llm: { model: string };
        tts: { voice: VoiceSummary; language: string; accent: string | null; speed: number };
    }
    // Saved before platform models, or nothing saved: one line is all we know.
    | { kind: "other"; text: string };

function label(options: PlatformCatalogOption[], id: string): string {
    return options.find((option) => option.id === id)?.label ?? id;
}

/** The persona of a voice name; Chirp 3 HD voices share Gemini Live's names. */
function voiceSummary(name: string, catalog: PlatformModelCatalog): VoiceSummary {
    const option = catalog.realtime.voices.find((voice) => voice.id === name);
    const style = option?.description ?? null;
    const toneId = voiceTone(style);
    const gender = option?.gender ?? null;
    return {
        name: option?.label ?? name,
        gender: gender ? gender.charAt(0).toUpperCase() + gender.slice(1) : null,
        style,
        tone: VOICE_TONES.find((tone) => tone.id === toneId)?.label ?? null,
        recommended: Boolean(option?.recommended),
    };
}

export function summarizePlatformConfiguration(
    configuration: unknown,
    catalog: PlatformModelCatalog,
): ConfigurationSummary {
    const stored = configuration && typeof configuration === "object"
        ? (configuration as Record<string, unknown>)
        : {};
    if (stored.mode !== "platform") {
        return { kind: "other", text: describePlatformConfiguration(configuration, catalog) };
    }
    const { state } = platformFormStateFromConfiguration(configuration, catalog);
    const mode = label(catalog.modes, state.pipelineMode);
    if (state.pipelineMode === "realtime") {
        return {
            kind: "realtime",
            mode,
            model: label(catalog.realtime.models, state.realtime.model),
            language: languageLabel(state.realtime.language),
            voice: voiceSummary(state.realtime.voice, catalog),
        };
    }
    const { pipeline } = catalog;
    // An accent only means something when the language has several.
    const siblings = localesByLanguage(pipeline.tts.languages).get(state.tts.language.split("-")[0]) ?? [];
    return {
        kind: "pipeline",
        mode,
        stt: { model: label(pipeline.stt.models, state.stt.model), language: languageLabel(state.stt.language) },
        llm: { model: label(pipeline.llm.models, state.llm.model) },
        tts: {
            voice: voiceSummary(state.tts.voice.split("-").pop() ?? state.tts.voice, catalog),
            language: languageLabel(state.tts.language),
            accent: siblings.length > 1 ? accentLabel(state.tts.language) : null,
            speed: state.tts.speed,
        },
    };
}
