import { describe, expect, it } from "vitest";

import { staffPhoneLine, transferHint } from "./transferNumber";

const check = (over: Partial<Parameters<typeof transferHint>[0] & object> = {}) => ({
    ok: true,
    value: "+353871234567",
    display: "+353 87 123 4567",
    kind: "Irish mobile",
    error: null,
    is_sip: false,
    is_demo: false,
    ...over,
});

describe("transferHint", () => {
    it("says how a good number is saved", () => {
        expect(transferHint(check())).toEqual({ tone: "ok", text: "✓ Irish mobile · saved as +353 87 123 4567" });
    });

    it("gives the server's reason for a number that can't be used", () => {
        expect(transferHint(check({ ok: false, value: "", error: "That number is too short." }))).toEqual({
            tone: "error",
            text: "That number is too short.",
        });
    });

    it("warns about the demo number", () => {
        expect(transferHint(check({ is_demo: true }))).toEqual({
            tone: "warn",
            text: "Demo number – change it before a live transfer",
        });
    });

    it("keeps a phone system address as typed", () => {
        expect(transferHint(check({ is_sip: true, value: "PJSIP/101", display: "PJSIP/101" }))?.text).toBe(
            "✓ Phone system address · dialled as typed",
        );
    });

    it("shows nothing before a check or for an empty box", () => {
        expect(transferHint(null)).toBeNull();
        expect(transferHint(check({ value: "" }))).toBeNull();
    });
});

describe("staffPhoneLine", () => {
    it("says what the staff phone shows", () => {
        expect(staffPhoneLine({ show_caller_number: true, staff_phone_shows: "caller", providers: ["twilio"] })).toMatch(
            /^Your phone shows the caller's number/,
        );
        expect(staffPhoneLine({ show_caller_number: false, staff_phone_shows: "agent", providers: ["twilio"] })).toBe(
            "Your phone shows your agent's number.",
        );
        expect(staffPhoneLine({ show_caller_number: true, staff_phone_shows: "agent", providers: ["plivo"] })).toMatch(
            /doesn't let us show the caller's/,
        );
        expect(staffPhoneLine({ show_caller_number: true, staff_phone_shows: "unknown", providers: [] })).toMatch(
            /^Where your phone provider allows it/,
        );
    });
});
