import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { UnsavedChangesProvider } from "@/context/UnsavedChangesContext";

import {
    CallSummaryEmailSection,
    callSummaryProblem,
    MAX_CALL_SUMMARY_RECIPIENTS,
    parseRecipients,
    savedRecipients,
} from "./CallSummaryEmailSection";

vi.mock("@/lib/auth", () => ({
    useAuth: () => ({ user: { id: "1", provider: "local", email: "owner@bloom.ie" } }),
}));

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

    it("saves only usable addresses while summaries are off", () => {
        expect(savedRecipients(true, ["a@bloom.ie", "nope"])).toEqual(["a@bloom.ie", "nope"]);
        expect(savedRecipients(false, ["a@bloom.ie", "nope"])).toEqual(["a@bloom.ie"]);
        const many = Array.from({ length: MAX_CALL_SUMMARY_RECIPIENTS + 2 }, (_, i) => `a${i}@bloom.ie`);
        expect(savedRecipients(false, many)).toHaveLength(MAX_CALL_SUMMARY_RECIPIENTS);
    });
});

describe("CallSummaryEmailSection", () => {
    const renderSection = (saved?: { enabled: boolean; recipients: string[] }) =>
        render(
            <UnsavedChangesProvider>
                <CallSummaryEmailSection saved={saved} />
            </UnsavedChangesProvider>,
        );

    it("starts from the user's own address when switched on", () => {
        renderSection();
        expect(screen.queryByLabelText("Send to")).toBeNull();

        fireEvent.click(screen.getByRole("switch", { name: "Email call summaries" }));

        expect(screen.getByLabelText("Send to")).toHaveProperty("value", "owner@bloom.ie");
    });

    it("keeps addresses already saved when switched back on", () => {
        renderSection({ enabled: false, recipients: ["desk@bloom.ie"] });

        fireEvent.click(screen.getByRole("switch", { name: "Email call summaries" }));

        expect(screen.getByLabelText("Send to")).toHaveProperty("value", "desk@bloom.ie");
    });
});
