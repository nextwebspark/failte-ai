import { describe, expect, it } from "vitest";

import { callOutcome } from "@/app/usage/callsView";
import type { FollowUpItem, TransferSettings } from "@/client/types.gen";
import { LINES_BUSY_OPTIONS, linesBusyNote } from "@/lib/transferNumber";

import {
    FOLLOW_UP_KINDS,
    FOLLOW_UP_WORDS,
    followUpDetail,
    followUpTitle,
    RESULT_WORDS,
    turnedAwayWords,
} from "./dashboardView";

function item(overrides: Partial<FollowUpItem> = {}): FollowUpItem {
    return {
        run_id: 1,
        workflow_id: 14,
        workflow_name: "Linen Quay",
        kind: "lines_busy",
        created_at: "2026-11-07T20:12:00Z",
        caller_number: "+353871111111",
        caller_name: null,
        callback_number: null,
        call_reason: null,
        duration_seconds: null,
        has_recording: true,
        repeat_count: null,
        first_call_at: null,
        done_at: null,
        done_by: null,
        summary: null,
        questions: [],
        lines_busy: "voicemail",
        voicemail_seconds: 14,
        ...overrides,
    };
}

describe("Lines were busy", () => {
    it("is a follow-up kind with its own words", () => {
        expect(FOLLOW_UP_KINDS).toContain("lines_busy");
        expect(FOLLOW_UP_WORDS.lines_busy.chip).toBe("Lines were busy");
        expect(RESULT_WORDS.lines_busy.label).toBe("Lines were busy");
    });

    it("says whether they left a voicemail", () => {
        expect(followUpTitle(item())).toBe("+353 87 111 1111 left a voicemail");
        expect(followUpDetail(item())).toBe(
            "All your lines were busy when they rang, so they didn't reach your agent. They left a voicemail (14s). Listen, then ring them back.",
        );
        const none = item({ lines_busy: "no_message", voicemail_seconds: null, has_recording: false });
        expect(followUpTitle(none)).toBe("Call back +353 87 111 1111");
        expect(followUpDetail(none)).toContain("They didn't leave a message.");
        expect(followUpDetail(item({ lines_busy: "told_busy" }))).toContain("They heard the busy message.");
    });

    it("shows on Calls with Home's rule for a forward someone answered", () => {
        expect(callOutcome({ disposition: "lines_busy", gathered_context: {} })).toEqual({
            label: "Lines were busy",
            tone: "warn",
        });
        expect(
            callOutcome({
                disposition: null,
                gathered_context: { mapped_call_disposition: "lines_busy", lines_busy_forward: { result: "answered" } },
            }),
        ).toEqual({ label: "Lines were busy · passed to your team", tone: "info" });
    });

    it("notes today's turned-away callers on Home", () => {
        expect(turnedAwayWords({ calls: 0, forwarded: 0, voicemails: 0 })).toBeNull();
        expect(turnedAwayWords(undefined)).toBeNull();
        expect(turnedAwayWords({ calls: 1, forwarded: 0, voicemails: 0 })).toBe(
            "1 caller rang while all your lines were busy today.",
        );
        expect(turnedAwayWords({ calls: 3, forwarded: 1, voicemails: 2 })).toBe(
            "3 callers rang while all your lines were busy today (1 put through to your team, 2 voicemails).",
        );
    });
});

describe("When all lines are busy", () => {
    const settings = (over: Partial<TransferSettings> = {}): TransferSettings => ({
        show_caller_number: true,
        staff_phone_shows: "caller",
        providers: ["twilio"],
        lines_busy: "forward",
        lines_busy_chosen: null,
        lines_busy_busy_line_only: [],
        ...over,
    });

    it("offers the three choices", () => {
        expect(LINES_BUSY_OPTIONS.map((o) => o.value)).toEqual(["forward", "voicemail", "busy_message"]);
        expect(LINES_BUSY_OPTIONS.map((o) => o.label)).toEqual([
            "Put them through to your team",
            "Take a voicemail",
            "Just say we're busy",
        ]);
    });

    it("explains when the choice can't apply", () => {
        expect(linesBusyNote(settings(), "")).toContain("Add a number above");
        expect(linesBusyNote(settings(), "087 123 4567")).toContain("Only while you're open");
        expect(
            linesBusyNote(settings({ lines_busy: "voicemail", lines_busy_busy_line_only: ["plivo"] }), ""),
        ).toContain("Your phone provider (Plivo) can only say the lines are busy.");
        expect(linesBusyNote(settings({ lines_busy: "busy_message" }), "")).toBe(
            "These callers show up in Follow-ups as “Lines were busy”.",
        );
    });
});
