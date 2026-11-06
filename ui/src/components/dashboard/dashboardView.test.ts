import { describe, expect, it } from "vitest";

import type { FollowUpItem } from "@/client/types.gen";

import {
    busiestHour,
    callBackNumber,
    callLength,
    callWhen,
    changeWords,
    clockTime,
    dayLine,
    followUpDetail,
    followUpTitle,
    hourWindow,
    lastCallWords,
    notAnsweringWords,
    rangeSentence,
    telHref,
    waitWords,
} from "./dashboardView";

const DUBLIN = "Europe/Dublin";
// Thursday 5 November 2026, 13:41 in Dublin (GMT in winter).
const NOW = new Date("2026-11-05T13:41:00Z");

function item(overrides: Partial<FollowUpItem> = {}): FollowUpItem {
    return {
        run_id: 1,
        workflow_id: 14,
        workflow_name: "Bia Bistro bookings",
        kind: "callback",
        created_at: "2026-11-05T10:42:00Z",
        caller_number: "+353871234567",
        caller_name: null,
        callback_number: null,
        call_reason: null,
        duration_seconds: 108,
        has_recording: true,
        repeat_count: null,
        first_call_at: null,
        done_at: null,
        done_by: null,
        ...overrides,
    };
}

describe("dates and times", () => {
    it("writes the day the Irish way", () => {
        expect(dayLine(NOW, DUBLIN)).toBe("Thursday 5 November");
        expect(rangeSentence("today", NOW, DUBLIN)).toBe("Here's how your phone agent did today, Thursday 5 November.");
        expect(rangeSentence("7d", NOW, DUBLIN)).toBe("Here's how your phone agent did in the last 7 days.");
    });

    it("uses the 24-hour clock in the business's zone", () => {
        expect(clockTime("2026-11-05T13:41:00Z", DUBLIN)).toBe("13:41");
        expect(clockTime("2026-11-05T13:41:00Z", "America/New_York")).toBe("08:41");
    });

    it("says today, yesterday or the date", () => {
        expect(callWhen("2026-11-05T09:05:00Z", DUBLIN, NOW)).toBe("09:05");
        expect(callWhen("2026-11-04T18:30:00Z", DUBLIN, NOW)).toBe("Yesterday 18:30");
        expect(callWhen("2026-11-02T18:30:00Z", DUBLIN, NOW)).toBe("Mon 2 Nov, 18:30");
    });

    it("says how long something waited", () => {
        expect(waitWords(45)).toBe("45 min");
        expect(waitWords(150)).toBe("2 h 30 min");
        expect(waitWords(120)).toBe("2 h");
        expect(waitWords(60 * 50)).toBe("2 days");
        expect(lastCallWords(null, NOW)).toBe("No calls yet");
        expect(lastCallWords("2026-11-05T11:41:00Z", NOW)).toBe("Last call 2 h ago");
    });

    it("writes call length with the Calls page's formatter", () => {
        expect(callLength(108)).toBe("1m 48s");
        expect(callLength(0)).toBeNull();
        expect(callLength(null)).toBeNull();
    });
});

describe("the change on last week", () => {
    it("names last week's day for today", () => {
        expect(changeWords("today", 8, NOW, DUBLIN)).toEqual({ sign: "up", amount: "+8", rest: " on last Thursday" });
        expect(changeWords("7d", -3, NOW, DUBLIN)).toEqual({ sign: "down", amount: "−3", rest: " on the 7 days before" });
        expect(changeWords("30d", 0, NOW, DUBLIN)?.rest).toBe("Same as the 30 days before");
    });

    it("is hidden when the API leaves it out", () => {
        expect(changeWords("today", null, NOW, DUBLIN)).toBeNull();
    });
});

describe("follow-up wording", () => {
    it("titles each kind plainly", () => {
        expect(followUpTitle(item({ caller_name: "Sinéad O'Brien" }))).toBe("Call back Sinéad O'Brien");
        expect(followUpTitle(item())).toBe("Call back +353871234567");
        expect(followUpTitle(item({ kind: "transfer_not_answered" }))).toBe("Transfer not answered");
        expect(followUpTitle(item({ kind: "repeat_caller", repeat_count: 3 }))).toBe("+353871234567 rang 3 times");
    });

    it("shows what the caller wanted, or says plainly what happened", () => {
        expect(followUpDetail(item({ call_reason: "Change Saturday to 7 people" }), DUBLIN, NOW)).toBe(
            "Change Saturday to 7 people",
        );
        expect(followUpDetail(item({ kind: "transfer_not_answered" }), DUBLIN, NOW)).toMatch(/nobody picked up/);
        expect(
            followUpDetail(
                item({ kind: "repeat_caller", repeat_count: 2, first_call_at: "2026-11-05T09:00:00Z" }),
                DUBLIN,
                NOW,
            ),
        ).toBe("Rang 2 times since 09:00 and didn't reach anyone.");
    });

    it("rings back the number the caller asked for first", () => {
        expect(callBackNumber(item({ callback_number: "087 000 0009" }))).toBe("087 000 0009");
        expect(callBackNumber(item())).toBe("+353871234567");
        expect(telHref("+353 87 123 4567")).toBe("tel:+353871234567");
    });

    it("explains why the agent isn't answering, with a fix", () => {
        expect(notAnsweringWords("no_credit").fix.href).toBe("/billing");
        expect(notAnsweringWords("no_number").detail).toMatch(/No phone number/);
        expect(notAnsweringWords("agent_off").detail).toMatch(/switched off/);
    });
});

describe("calls per hour", () => {
    it("shows 08:00 to 20:00, widened to any busy hour", () => {
        const hours = Array(24).fill(0);
        expect(hourWindow(hours)).toEqual({ start: 8, end: 20 });
        hours[6] = 1;
        hours[22] = 2;
        expect(hourWindow(hours)).toEqual({ start: 6, end: 22 });
    });

    it("labels the busiest hour only when it stands out", () => {
        const flat = Array(24).fill(0);
        flat[9] = 2;
        flat[13] = 2;
        expect(busiestHour(flat)).toBeNull();
        const peaked = Array(24).fill(0);
        peaked[9] = 1;
        peaked[10] = 1;
        peaked[13] = 6;
        expect(busiestHour(peaked)).toBe(13);
        const tie = [...peaked];
        tie[19] = 6;
        expect(busiestHour(tie)).toBeNull();
    });
});
