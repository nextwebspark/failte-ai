// Test fixture: a small platform catalog in the shape the API returns.
import type { PlatformModelCatalog } from "@/client/types.gen";

export const platformCatalogFixture: PlatformModelCatalog = {
    enabled: true,
    locked: false,
    default_mode: "realtime",
    modes: [
        { id: "realtime", label: "Speech-to-Speech", description: "One model listens and speaks.", recommended: true },
        { id: "pipeline", label: "Speech-to-Text → LLM → Text-to-Speech", description: "Separate steps." },
    ],
    realtime: {
        models: [{ id: "google/gemini-live-2.5-flash-native-audio", label: "Gemini Live 2.5 Flash", recommended: true }],
        voices: [
            { id: "Charon", label: "Charon", gender: "male", description: "Informative", preview_url: "/api/v1/user/configurations/voices/google/preview?voice_id=en-US-Chirp3-HD-Charon" },
            { id: "Kore", label: "Kore", gender: "female", description: "Firm", preview_url: null },
        ],
        languages: ["en", "de", "fr"],
        defaults: { model: "google/gemini-live-2.5-flash-native-audio", voice: "Charon", language: "en" },
    },
    pipeline: {
        llm: {
            models: [
                { id: "gemini-3.5-flash", label: "Gemini 3.5 Flash", recommended: true },
                { id: "gemini-3.1-flash-lite", label: "Gemini 3.1 Flash Lite" },
            ],
            temperature_range: { min: 0, max: 2, step: 0.1 },
            defaults: { model: "gemini-3.5-flash", temperature: 0.1 },
        },
        stt: {
            models: [
                { id: "chirp_3", label: "Chirp 3", recommended: true, languages: ["en-US", "en-GB", "cy-GB"] },
                { id: "latest_long", label: "Latest long", languages: ["en-US", "en-GB"] },
            ],
            languages: ["cy-GB", "en-GB", "en-US"],
            defaults: { model: "chirp_3", language: "en-US" },
        },
        tts: {
            models: [{ id: "chirp_3_hd", label: "Chirp 3 HD", recommended: true }],
            languages: ["en-GB", "en-US"],
            speed_range: { min: 0.25, max: 2, step: 0.05 },
            voice_catalog: "google",
            defaults: { model: "chirp_3_hd", voice: "en-US-Chirp3-HD-Charon", language: "en-US", speed: 1 },
        },
    },
};
