import { describe, expect, it } from "vitest";

import type { PlatformModelCatalog } from "@/client/types.gen";
import { platformCatalogFixture } from "@/lib/__fixtures__/platformCatalog";

import { voiceChoices, voicePreviewPath, withVoice } from "./voiceOptions";

const catalog: PlatformModelCatalog = {
    ...platformCatalogFixture,
    realtime: {
        ...platformCatalogFixture.realtime,
        voices: [
            { id: "Charon", label: "Charon", gender: "male", description: "Informative", recommended: true },
            { id: "Kore", label: "Kore", gender: "female", description: "Firm", recommended: true },
            { id: "Puck", label: "Puck", gender: "male", description: "Upbeat", recommended: true },
            { id: "Aoede", label: "Aoede", gender: "female", description: "Breezy", recommended: true },
            { id: "Zephyr", label: "Zephyr", gender: "female", description: "Bright" },
        ],
    },
};

const realtime = (voice: string, language = "en") => ({
    version: 2,
    mode: "platform",
    platform: {
        pipeline_mode: "realtime",
        realtime: { model: "google/gemini-live-2.5-flash-native-audio", voice, language },
    },
});

const pipeline = (voice: string, language = "en-GB") => ({
    version: 2,
    mode: "platform",
    platform: {
        pipeline_mode: "pipeline",
        pipeline: {
            llm: { model: "gemini-3.5-flash", temperature: 0.1 },
            stt: { model: "chirp_3", language },
            tts: { model: "chirp_3_hd", voice, language, speed: 1 },
        },
    },
});

describe("voiceChoices", () => {
    it("offers three other live voices, mixing genders, previewed with the Chirp 3 HD voice of the same name", () => {
        const choices = voiceChoices(realtime("Charon"), catalog);
        expect(choices?.current).toMatchObject({ value: "Charon", name: "Charon", gender: "Male", previewVoiceId: "en-US-Chirp3-HD-Charon" });
        expect(choices?.alternatives.map((v) => v.value)).toEqual(["Kore", "Puck", "Aoede"]);
        expect(choices?.alternatives.map((v) => v.gender)).toEqual(["Female", "Male", "Female"]);
        expect(choices?.alternatives.every((v) => v.value !== "Charon")).toBe(true);
    });

    it("previews a live voice in its language's accent", () => {
        expect(voiceChoices(realtime("Kore", "de"), catalog)?.current.previewVoiceId).toBe("de-DE-Chirp3-HD-Kore");
    });

    it("offers text-to-speech voices in the agent's own language", () => {
        const choices = voiceChoices(pipeline("en-GB-Chirp3-HD-Kore"), catalog);
        expect(choices?.current).toMatchObject({ value: "en-GB-Chirp3-HD-Kore", name: "Kore", previewVoiceId: "en-GB-Chirp3-HD-Kore" });
        expect(choices?.alternatives.map((v) => v.value)).toEqual([
            "en-GB-Chirp3-HD-Charon",
            "en-GB-Chirp3-HD-Aoede",
            "en-GB-Chirp3-HD-Puck",
        ]);
        expect(choices?.alternatives.every((v) => v.previewVoiceId === v.value)).toBe(true);
    });

    it("offers nothing for a setup that isn't a platform one", () => {
        expect(voiceChoices({ mode: "byok" }, catalog)).toBeNull();
        expect(voiceChoices(null, catalog)).toBeNull();
    });
});

describe("withVoice", () => {
    it("changes only the voice", () => {
        expect(withVoice(realtime("Charon"), catalog, "Kore")).toEqual(realtime("Kore"));
        expect(withVoice(pipeline("en-GB-Chirp3-HD-Kore"), catalog, "en-GB-Chirp3-HD-Puck")).toEqual(
            pipeline("en-GB-Chirp3-HD-Puck"),
        );
    });
});

it("builds the preview path with the voice escaped", () => {
    expect(voicePreviewPath(12, "en-GB-Chirp3-HD-Kore")).toBe("/api/v1/workflow/12/voice-preview?voice_id=en-GB-Chirp3-HD-Kore");
});
