import { describe, expect, it } from "vitest";

import { platformCatalogFixture as catalog } from "@/lib/platformCatalog.fixture";
import {
    buildPlatformConfiguration,
    defaultPlatformFormState,
    languageLabel,
    parsePlatformConfiguration,
    sttLanguagesFor,
    validatePlatformFormState,
    voiceLocale,
} from "@/lib/platformModelConfig";

describe("platform model configuration", () => {
    it("starts from the catalog defaults", () => {
        const state = defaultPlatformFormState(catalog);
        expect(state.pipelineMode).toBe("realtime");
        expect(state.realtime).toEqual({
            model: "google/gemini-live-2.5-flash-native-audio",
            voice: "Charon",
            language: "en",
        });
        expect(state.tts.voice).toBe("en-US-Chirp3-HD-Charon");
        expect(validatePlatformFormState(state, catalog)).toEqual([]);
    });

    it("round-trips a stored platform configuration", () => {
        const stored = {
            version: 2,
            mode: "platform",
            platform: {
                pipeline_mode: "pipeline",
                realtime: { model: "google/gemini-live-2.5-flash-native-audio", voice: "Kore", language: "de" },
                pipeline: {
                    llm: { model: "gemini-3.1-flash-lite", temperature: null },
                    stt: { model: "latest_long", language: "en-GB" },
                    tts: { model: "chirp_3_hd", voice: "en-GB-Chirp3-HD-Kore", language: "en-GB", speed: 1.2 },
                },
            },
        };

        const parsed = parsePlatformConfiguration(stored, catalog);

        expect(parsed.replacedMode).toBeNull();
        expect(parsed.state.pipelineMode).toBe("pipeline");
        expect(parsed.state.llm.temperature).toBeNull();
        expect(buildPlatformConfiguration(parsed.state)).toEqual(stored);
    });

    it("fills missing fields of a partial platform configuration", () => {
        const parsed = parsePlatformConfiguration(
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
        [{ mode: "dograh", dograh: {} }, "dograh"],
        [{ mode: "byok", byok: {} }, "byok"],
        [null, "empty"],
    ])("starts a non-platform configuration from defaults", (stored, replaced) => {
        const parsed = parsePlatformConfiguration(stored, catalog);
        expect(parsed.replacedMode).toBe(replaced);
        expect(parsed.state).toEqual(defaultPlatformFormState(catalog));
    });

    it("never sends keys or infrastructure", () => {
        const body = JSON.stringify(buildPlatformConfiguration(defaultPlatformFormState(catalog)));
        expect(body).not.toMatch(/api_key|credentials|project_id|location/);
    });

    it("validates speech languages per model and voice locale", () => {
        const state = defaultPlatformFormState(catalog);
        state.pipelineMode = "pipeline";
        state.stt = { model: "latest_long", language: "cy-GB" };
        state.tts = { ...state.tts, voice: "en-US-Chirp3-HD-Kore", language: "en-GB" };

        const errors = validatePlatformFormState(state, catalog);

        expect(errors).toHaveLength(2);
        expect(sttLanguagesFor(catalog, "chirp_3")).toContain("cy-GB");
        expect(sttLanguagesFor(catalog, "latest_long")).not.toContain("cy-GB");
    });

    it("validates ranges", () => {
        const state = defaultPlatformFormState(catalog);
        state.pipelineMode = "pipeline";
        state.llm.temperature = 3;
        state.tts.speed = 5;
        expect(validatePlatformFormState(state, catalog)).toHaveLength(2);
    });

    it("reads voice locales and language names", () => {
        expect(voiceLocale("en-GB-Chirp3-HD-Kore")).toBe("en-GB");
        expect(voiceLocale("cmn-CN-Chirp3-HD-Kore")).toBe("cmn-CN");
        expect(voiceLocale("Kore")).toBeNull();
        expect(languageLabel("de")).toMatch(/German/);
        expect(languageLabel("zz")).toBe("zz");
    });
});
