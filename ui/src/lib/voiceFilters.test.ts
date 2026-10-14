import { describe, expect, it } from "vitest";

import { accentLabel, localesByLanguage, voiceTone } from "@/lib/voiceFilters";

// Google's style words for the 30 Gemini Live / Chirp 3 HD voices.
const GOOGLE_STYLES = [
    "Informative", "Firm", "Upbeat", "Breezy", "Excitable", "Bright", "Youthful", "Breathy",
    "Easy-going", "Clear", "Smooth", "Gravelly", "Soft", "Mature", "Even", "Forward",
    "Friendly", "Gentle", "Casual", "Warm", "Lively", "Knowledgeable",
];

describe("voiceFilters", () => {
    it("puts every Google style word in a tone", () => {
        expect(GOOGLE_STYLES.filter((style) => voiceTone(style) === null)).toEqual([]);
        expect(voiceTone("Firm")).toBe("professional");
        expect(voiceTone(undefined)).toBeNull();
    });

    it("names accents the way customers say them", () => {
        expect(accentLabel("en-GB")).toBe("British");
        expect(accentLabel("en-IN")).toBe("Indian");
        expect(accentLabel("pt-BR")).toBe("Brazil");
    });

    it("groups locales by language", () => {
        const groups = localesByLanguage(["en-US", "de-DE", "en-GB", "en-AU", "en-IN"]);
        expect(groups.get("en")).toEqual(["en-US", "en-AU", "en-GB", "en-IN"]);
        expect(groups.get("de")).toEqual(["de-DE"]);
    });
});
