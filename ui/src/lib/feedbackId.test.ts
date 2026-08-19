import { describe, expect, it } from "vitest";

import { feedbackId } from "./feedbackId";

describe("feedbackId", () => {
    it("never repeats, even within one millisecond", () => {
        // The regression: a failed synthesis emitted two pipeline errors in the
        // same millisecond, both got id `error-<ts>`, and React rendered one row
        // instead of two with a duplicate-key console error.
        const ids = Array.from({ length: 500 }, () => feedbackId("error"));

        expect(new Set(ids).size).toBe(ids.length);
    });

    it("keeps the prefix so ids stay readable in a transcript dump", () => {
        expect(feedbackId("bot")).toMatch(/^bot-\d+-\d+$/);
    });

    it("does not collide across prefixes", () => {
        const ids = [feedbackId("user"), feedbackId("bot"), feedbackId("ttfb")];

        expect(new Set(ids).size).toBe(3);
    });
});
