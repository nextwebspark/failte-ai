import { describe, expect, it } from "vitest";

import { platformCatalogFixture as catalog } from "@/lib/__fixtures__/platformCatalog";
import { summarizePlatformConfiguration } from "@/lib/platformModelSummary";

describe("summarizePlatformConfiguration", () => {
    it("describes a speech-to-speech setup with the voice persona", () => {
        const summary = summarizePlatformConfiguration(
            {
                version: 2,
                mode: "platform",
                platform: {
                    pipeline_mode: "realtime",
                    realtime: { model: "google/gemini-live-2.5-flash-native-audio", voice: "Kore", language: "en" },
                },
            },
            catalog,
        );

        expect(summary).toEqual({
            kind: "realtime",
            mode: "Speech-to-Speech",
            model: "Gemini Live 2.5 Flash",
            language: "English",
            voice: { name: "Kore", gender: "Female", style: "Firm", tone: "Calm & professional", recommended: false },
        });
    });

    it("describes each step of a pipeline, with the accent of the voice", () => {
        const summary = summarizePlatformConfiguration(
            {
                version: 2,
                mode: "platform",
                platform: {
                    pipeline_mode: "pipeline",
                    pipeline: {
                        llm: { model: "gemini-3.1-flash-lite", temperature: 0.1 },
                        stt: { model: "chirp_3", language: "en-US" },
                        tts: { model: "chirp_3_hd", voice: "en-GB-Chirp3-HD-Charon", language: "en-GB", speed: 1.2 },
                    },
                },
            },
            catalog,
        );

        expect(summary).toMatchObject({
            kind: "pipeline",
            stt: { model: "Chirp 3", language: "American English" },
            llm: { model: "Gemini 3.1 Flash Lite" },
            tts: { voice: { name: "Charon", gender: "Male", style: "Informative" }, accent: "British", speed: 1.2 },
        });
    });

    it("has no accent for a language with one locale", () => {
        const summary = summarizePlatformConfiguration(
            {
                version: 2,
                mode: "platform",
                platform: {
                    pipeline_mode: "pipeline",
                    pipeline: {
                        llm: { model: "gemini-3.5-flash" },
                        stt: { model: "chirp_3", language: "en-US" },
                        tts: { model: "chirp_3_hd", voice: "de-DE-Chirp3-HD-Kore", language: "de-DE", speed: 1 },
                    },
                },
            },
            catalog,
        );

        expect(summary).toMatchObject({ kind: "pipeline", tts: { accent: null } });
    });

    it("falls back to one line for older setups", () => {
        expect(summarizePlatformConfiguration({ version: 2, mode: "dograh" }, catalog)).toEqual({
            kind: "other",
            text: "Older hosted setup",
        });
    });
});
