import { describe, expect, it } from "vitest";

import { detailFromError } from "./apiError";

describe("detailFromError", () => {
    it("returns a string detail, such as an Agent Builder 502", () => {
        expect(
            detailFromError({ detail: "Could not generate an agent from this description." }, "fallback"),
        ).toBe("Could not generate an agent from this description.");
    });

    it("joins FastAPI validation messages", () => {
        expect(
            detailFromError({ detail: [{ msg: "String should have at most 200 characters" }] }, "fallback"),
        ).toBe("String should have at most 200 characters");
    });

    it("falls back when there is no usable detail", () => {
        expect(detailFromError(undefined, "fallback")).toBe("fallback");
        expect(detailFromError({}, "fallback")).toBe("fallback");
    });
});
