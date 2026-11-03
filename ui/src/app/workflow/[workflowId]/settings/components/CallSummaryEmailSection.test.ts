import { describe, expect, it } from "vitest";

import { callSummaryProblem, MAX_CALL_SUMMARY_RECIPIENTS, parseRecipients } from "./CallSummaryEmailSection";

describe("call summary recipients", () => {
    it("reads a comma-separated list without blanks", () => {
        expect(parseRecipients(" a@bloom.ie, b@bloom.ie;; c@bloom.ie ")).toEqual(["a@bloom.ie", "b@bloom.ie", "c@bloom.ie"]);
        expect(parseRecipients("  ")).toEqual([]);
    });

    it("needs valid addresses only while summaries are on", () => {
        expect(callSummaryProblem(false, [])).toBeNull();
        expect(callSummaryProblem(true, ["a@bloom.ie"])).toBeNull();
        expect(callSummaryProblem(true, [])).toBe("Add an email address for call summaries");
        expect(callSummaryProblem(true, ["a@bloom.ie", "nope"])).toBe("Check the call summary email addresses");
        const tooMany = Array.from({ length: MAX_CALL_SUMMARY_RECIPIENTS + 1 }, (_, i) => `a${i}@bloom.ie`);
        expect(callSummaryProblem(true, tooMany)).toMatch(/at most/);
    });
});
