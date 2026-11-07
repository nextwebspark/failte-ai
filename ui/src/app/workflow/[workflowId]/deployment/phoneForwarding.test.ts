import { describe, expect, it } from "vitest";

import { displayNumber, forwardingCode, UNDO_CODE } from "./phoneForwarding";

describe("forwardingCode", () => {
    it("builds the standard mobile codes for the agent's number", () => {
        expect(forwardingCode("+35315550142", "no_answer")).toBe("**61*+35315550142**20#");
        expect(forwardingCode("+35315550142", "busy")).toBe("**67*+35315550142#");
        expect(forwardingCode("+35315550142", "all")).toBe("**21*+35315550142#");
    });

    it("has no code for outside opening hours", () => {
        expect(forwardingCode("+35315550142", "outside_hours")).toBeNull();
    });

    it("drops spaces a stored number might carry", () => {
        expect(forwardingCode("+353 1 555 0142", "all")).toBe("**21*+35315550142#");
    });

    it("undoes every forward with ##002#", () => {
        expect(UNDO_CODE).toBe("##002#");
    });
});

describe("displayNumber", () => {
    it("spaces Irish numbers the way people write them", () => {
        expect(displayNumber("+35315550142")).toBe("+353 1 555 0142");
        expect(displayNumber("+353871234567")).toBe("+353 87 123 4567");
        expect(displayNumber("+353215550100")).toBe("+353 21 555 0100");
    });

    it("leaves other numbers alone", () => {
        expect(displayNumber("+14155550100")).toBe("+14155550100");
    });
});
