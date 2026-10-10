import { describe, expect, it } from "vitest";

import { platformCatalogFixture as catalog } from "@/lib/__fixtures__/platformCatalog";
import {
    buildPlatformConfiguration,
    defaultPlatformFormState,
    describePlatformConfiguration,
    isVoiceFor,
    languageLabel,
    platformFormStateFromConfiguration,
    platformOverrideSeed,
    sttLanguageForModel,
    sttLanguagesFor,
    validatePlatformFormState,
    voiceInLanguage,
    voiceLocale,
} from "@/lib/platformModelConfig";

const PIPELINE = {
    version: 2,
    mode: "platform",
    platform: {
        pipeline_mode: "pipeline",
        pipeline: {
            llm: { model: "gemini-3.1-flash-lite", temperature: null },
            stt: { model: "latest_long", language: "en-GB" },
            tts: { model: "chirp_3_hd", voice: "en-GB-Chirp3-HD-Kore", language: "en-GB", speed: 1.2 },
        },
    },
};

const REALTIME = {
    version: 2,
    mode: "platform",
    platform: {
        pipeline_mode: "realtime",
        realtime: { model: "google/gemini-live-2.5-flash-native-audio", voice: "Kore", language: "de" },
    },
};

function pipelineState() {
    const state = defaultPlatformFormState(catalog);
    state.pipelineMode = "pipeline";
    return state;
}

describe("platform model configuration", () => {
    it("starts from the catalog defaults", () => {
        const state = defaultPlatformFormState(catalog);
        expect(state.pipelineMode).toBe("realtime");
        expect(state.realtime).toEqual({
            model: "google/gemini-live-2.5-flash-native-audio",
            voice: "Charon",
            language: "en",
        });
        expect(validatePlatformFormState(state, catalog)).toEqual([]);
        expect(validatePlatformFormState(pipelineState(), catalog)).toEqual([]);
    });

    it.each([["pipeline", PIPELINE], ["realtime", REALTIME]])(
        "round-trips a stored %s configuration",
        (_mode, stored) => {
            const parsed = platformFormStateFromConfiguration(stored, catalog);
            expect(parsed.migratedFrom).toBeNull();
            expect(buildPlatformConfiguration(parsed.state)).toEqual(stored);
        },
    );

    it("sends only the active mode's block", () => {
        const state = defaultPlatformFormState(catalog);
        // An inactive pipeline the server would reject must not be sent.
        state.tts.language = "en-GB";
        expect(buildPlatformConfiguration(state).platform).toEqual({
            pipeline_mode: "realtime",
            realtime: state.realtime,
        });
    });

    it("keeps a null temperature and defaults a malformed one", () => {
        const nullTemperature = platformFormStateFromConfiguration(PIPELINE, catalog);
        expect(nullTemperature.state.llm.temperature).toBeNull();

        const malformed = structuredClone(PIPELINE);
        (malformed.platform.pipeline.llm as Record<string, unknown>).temperature = "0.5";
        expect(platformFormStateFromConfiguration(malformed, catalog).state.llm.temperature).toBe(0.1);
    });

    it("fills missing fields of a partial platform configuration", () => {
        const parsed = platformFormStateFromConfiguration(
            { mode: "platform", platform: { pipeline_mode: "realtime", realtime: { voice: "Kore" } } },
            catalog,
        );
        expect(parsed.state.realtime).toEqual({
            model: "google/gemini-live-2.5-flash-native-audio",
            voice: "Kore",
            language: "en",
        });
        expect(parsed.state.stt).toEqual({ model: "chirp_3", language: "en-US" });
    });

    it.each([
        ["dograh", { mode: "dograh", dograh: { language: "de" } }, "de", "en-US"],
        [
            "byok",
            { mode: "byok", byok: { mode: "pipeline", pipeline: { stt: { provider: "deepgram", language: "en-GB" } } } },
            "en",
            "en-GB",
        ],
        [
            "byok",
            { mode: "byok", byok: { mode: "realtime", realtime: { realtime: { voice: "Kore", language: "fr" } } } },
            "fr",
            "en-US",
        ],
        ["empty", null, "en", "en-US"],
    ])("starts a %s configuration from defaults, keeping its language", (from, stored, realtime, stt) => {
        const parsed = platformFormStateFromConfiguration(stored, catalog);
        expect(parsed.migratedFrom).toBe(from);
        expect(parsed.state.realtime.language).toBe(realtime);
        expect(parsed.state.stt.language).toBe(stt);
        expect(validatePlatformFormState(parsed.state, catalog)).toEqual([]);
    });

    it("keeps a BYOK Gemini Live voice the catalog offers", () => {
        const parsed = platformFormStateFromConfiguration(
            { mode: "byok", byok: { mode: "realtime", realtime: { realtime: { voice: "Kore" } } } },
            catalog,
        );
        expect(parsed.state.realtime.voice).toBe("Kore");
    });

    it("never sends keys or infrastructure", () => {
        for (const state of [defaultPlatformFormState(catalog), pipelineState()]) {
            const body = JSON.stringify(buildPlatformConfiguration(state));
            expect(body).not.toMatch(/api_key|credentials|project_id|location/);
        }
    });

    it("checks speech languages per model", () => {
        const state = pipelineState();
        state.stt = { model: "latest_long", language: "cy-GB" };

        expect(validatePlatformFormState(state, catalog)).toEqual([
            "The speech-to-text model doesn't support this language. Pick another language or model.",
        ]);
        expect(sttLanguagesFor(catalog, "chirp_3")).toContain("cy-GB");
    });

    it.each([
        ["en-US-Chirp3-HD-Kore", "en-GB"],
        ["en-GB-Neural2-A", "en-GB"],
        ["Kore", "en-GB"],
    ])("rejects voice %s for language %s", (voice, language) => {
        const state = pipelineState();
        state.tts = { ...state.tts, voice, language };
        expect(validatePlatformFormState(state, catalog)).toEqual([
            "Choose a voice that speaks the selected voice language.",
        ]);
    });

    it("rejects a voice language the catalog doesn't offer", () => {
        const state = pipelineState();
        state.tts = { ...state.tts, voice: "fr-FR-Chirp3-HD-Kore", language: "fr-FR" };
        expect(validatePlatformFormState(state, catalog)).toEqual(["Choose a voice language."]);
    });

    it("rejects realtime choices outside the catalog", () => {
        const state = defaultPlatformFormState(catalog);
        state.realtime = { model: "other", voice: "Zephyr", language: "xx" };
        expect(validatePlatformFormState(state, catalog)).toEqual([
            "Choose a model.",
            "Choose a voice.",
            "Choose a language.",
        ]);
    });

    it("checks ranges", () => {
        const state = pipelineState();
        state.llm.temperature = 3;
        state.tts.speed = 5;
        expect(validatePlatformFormState(state, catalog)).toEqual([
            "Temperature must be between 0 and 2.",
            "Speed must be between 0.25 and 2.",
        ]);
    });

    it("keeps the voice persona when the voice language changes", () => {
        expect(voiceInLanguage(catalog, "chirp_3_hd", "en-US-Chirp3-HD-Kore", "en-GB")).toBe(
            "en-GB-Chirp3-HD-Kore",
        );
        expect(voiceInLanguage(catalog, "other", "en-US-Chirp3-HD-Kore", "en-GB")).toBe("");
    });

    it("keeps a speech-to-text language the new model serves", () => {
        expect(sttLanguageForModel(catalog, "latest_long", "en-GB")).toBe("en-GB");
        expect(sttLanguageForModel(catalog, "latest_long", "cy-GB")).toBe("en-US");
    });

    it("reads voice locales and language names", () => {
        expect(voiceLocale("en-GB-Chirp3-HD-Kore")).toBe("en-GB");
        expect(voiceLocale("cmn-CN-Chirp3-HD-Kore")).toBe("cmn-CN");
        expect(voiceLocale("Kore")).toBeNull();
        expect(isVoiceFor(catalog, "chirp_3_hd", "en-GB", "en-GB-Chirp3-HD-Kore")).toBe(true);
        expect(languageLabel("de")).toBe("German");
        expect(languageLabel("en-GB")).toBe("British English");
        expect(languageLabel("zz")).toBe("zz");
    });

    it.each([
        ["a platform override", REALTIME, REALTIME],
        ["no override", null, PIPELINE],
        ["no override", undefined, PIPELINE],
    ])("seeds an agent override from %s", (_case, saved, expected) => {
        expect(platformOverrideSeed(saved, PIPELINE)).toBe(expected);
    });

    it("seeds an agent override from its own legacy provider override", () => {
        const legacy = { mode: "byok", byok: {} };
        expect(platformOverrideSeed(legacy, PIPELINE)).toBe(legacy);
    });

    it("keeps a BYOK pipeline's mode, models, voice and language", () => {
        const parsed = platformFormStateFromConfiguration(
            {
                mode: "byok",
                byok: {
                    mode: "pipeline",
                    pipeline: {
                        llm: { provider: "google_vertex", model: "gemini-3.1-flash-lite" },
                        stt: { provider: "google", model: "latest_long", language: "en-GB" },
                        tts: { provider: "google", model: "chirp_3_hd", voice: "en-GB-Chirp3-HD-Kore", language: "en-GB", speed: 1.2 },
                    },
                },
            },
            catalog,
        );
        expect(parsed.state.pipelineMode).toBe("pipeline");
        expect(parsed.state.llm.model).toBe("gemini-3.1-flash-lite");
        expect(parsed.state.stt).toEqual({ model: "latest_long", language: "en-GB" });
        expect(parsed.state.tts).toMatchObject({ voice: "en-GB-Chirp3-HD-Kore", language: "en-GB", speed: 1.2 });
        // The other mode follows the same voice and language.
        expect(parsed.state.realtime).toMatchObject({ voice: "Kore", language: "en" });
        expect(validatePlatformFormState(parsed.state, catalog)).toEqual([]);
    });

    it("starts the mode that isn't stored from the workspace, else from the stored mode", () => {
        const workspaceGb = structuredClone(PIPELINE);
        workspaceGb.platform.pipeline.tts.voice = "en-GB-Chirp3-HD-Puck";
        const english = structuredClone(REALTIME);
        english.platform.realtime.language = "en";
        // Language and models from the workspace, the agent's own Kore persona.
        const fromWorkspace = platformFormStateFromConfiguration(english, catalog, workspaceGb);
        expect(fromWorkspace.state.tts).toMatchObject({ voice: "en-GB-Chirp3-HD-Kore", language: "en-GB" });
        expect(fromWorkspace.state.stt.language).toBe("en-GB");

        const fromMode = platformFormStateFromConfiguration(english, catalog);
        // Kore in the default English variant, not the default Charon.
        expect(fromMode.state.tts.voice).toBe("en-US-Chirp3-HD-Kore");

        const fromPipeline = platformFormStateFromConfiguration(PIPELINE, catalog);
        expect(fromPipeline.state.realtime).toMatchObject({ voice: "Kore", language: "en" });
    });

    it("keeps a BYOK Live model the catalog offers", () => {
        const parsed = platformFormStateFromConfiguration(
            {
                mode: "byok",
                byok: {
                    mode: "realtime",
                    realtime: { realtime: { model: "gemini-live-2.5-flash-native-audio", voice: "Kore" } },
                },
            },
            catalog,
        );
        expect(parsed.state.realtime.model).toBe("google/gemini-live-2.5-flash-native-audio");
    });

    it("keeps the agent's language when the workspace speaks another", () => {
        // A German speech-to-speech agent in an English pipeline workspace.
        const parsed = platformFormStateFromConfiguration(REALTIME, catalog, PIPELINE);
        expect(parsed.state.tts).toMatchObject({ language: "de-DE", voice: "de-DE-Chirp3-HD-Kore" });
    });

    it("keeps the agent's own Charon persona even though it is the default", () => {
        const charonPipeline = structuredClone(PIPELINE);
        charonPipeline.platform.pipeline.tts.voice = "en-GB-Chirp3-HD-Charon";
        const workspace = structuredClone(REALTIME);
        workspace.platform.realtime = { ...workspace.platform.realtime, voice: "Puck", language: "en" };
        const parsed = platformFormStateFromConfiguration(charonPipeline, catalog, workspace);
        expect(parsed.state.realtime.voice).toBe("Charon");
    });

    it("describes an older provider setup as what it runs", () => {
        expect(
            describePlatformConfiguration(
                {
                    mode: "byok",
                    byok: {
                        mode: "pipeline",
                        pipeline: {
                            llm: { model: "gemini-3.5-flash" },
                            tts: { voice: "en-GB-Chirp3-HD-Gacrux", language: "en-GB" },
                        },
                    },
                },
                catalog,
            ),
        ).toBe("Speech-to-Text → LLM → Text-to-Speech · Gemini 3.5 Flash · Gacrux · British English (older provider setup)");
        expect(describePlatformConfiguration(null, catalog)).toBe("Not set up yet");
    });

    it("describes a configuration in one line", () => {
        expect(describePlatformConfiguration(REALTIME, catalog)).toBe(
            "Speech-to-Speech · Gemini Live 2.5 Flash · Kore · German",
        );
        expect(describePlatformConfiguration(PIPELINE, catalog)).toBe(
            "Speech-to-Text → LLM → Text-to-Speech · Gemini 3.1 Flash Lite · Kore · British English",
        );
    });
});
