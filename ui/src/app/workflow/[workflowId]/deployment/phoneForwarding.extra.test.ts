import { describe, expect, it } from "vitest";

import { forwardingCode, isPublicNumber } from "./phoneForwarding";

describe("forwarding only to real phone numbers", () => {
    it("knows a full phone number from an extension or SIP address", () => {
        expect(isPublicNumber("+35315550142")).toBe(true);
        expect(isPublicNumber("+353 87 123 4567")).toBe(true);
        expect(isPublicNumber("7000")).toBe(false);
        expect(isPublicNumber("sip:7000@pbx.local")).toBe(false);
    });

    it("gives no forwarding code for an extension", () => {
        expect(forwardingCode("7000", "no_answer")).toBeNull();
        expect(forwardingCode("+35315550142", "no_answer")).toBe("**61*+35315550142**20#");
    });
});
