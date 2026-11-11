import { describe, expect, it } from "vitest";

import { parseAgentLanguages, serializeAgentLanguages, toggleAgentLanguage } from "./agentLanguages";

describe("agent languages", () => {
    it("always includes English and keeps the offered order", () => {
        expect(parseAgentLanguages("")).toEqual(["English"]);
        expect(parseAgentLanguages(null)).toEqual(["English"]);
        expect(parseAgentLanguages("polish, Irish, Klingon")).toEqual(["English", "Irish", "Polish"]);
    });

    it("saves English only as empty, so the prompt's fallback applies", () => {
        expect(serializeAgentLanguages(["English"])).toBe("");
        expect(serializeAgentLanguages(["Polish"])).toBe("English, Polish");
    });

    it("switches a language on and off, never English", () => {
        expect(toggleAgentLanguage("", "Polish")).toBe("English, Polish");
        expect(toggleAgentLanguage("English, Polish", "Polish")).toBe("");
        expect(toggleAgentLanguage("English, Polish", "English")).toBe("English, Polish");
        expect(toggleAgentLanguage("English, Polish", "Arabic")).toBe("English, Polish, Arabic");
    });
});
