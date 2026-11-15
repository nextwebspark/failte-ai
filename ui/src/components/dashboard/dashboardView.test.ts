import { describe, expect, it } from "vitest";

import type { FollowUpItem } from "@/client/types.gen";

import {
    afterHoursWords,
    agentLineLabel,
    appendAnswer,
    busiestHour,
    callBackNumber,
    callDayAndTime,
    callLength,
    callWhen,
    changeWords,
    clockTime,
    dayLine,
    FOLLOW_UP_KINDS,
    FOLLOW_UP_WORDS,
    followUpChip,
    followUpDetail,
    followUpKey,
    followUpTitle,
    hourSpan,
    hourWindow,
    lastCallWords,
    markKind,
    notAnsweringWords,
    openHoursLegend,
    openRangesWords,
    openRangeWords,
    primaryAgentId,
    rangeSentence,
    telHref,
    todayLine,
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
        summary: null,
        questions: [],
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
        expect(clockTime("2026-11-05T13:41:00Z", DUBLIN)).toBe("1:41 pm");
        expect(clockTime("2026-11-05T13:41:00Z", "America/New_York")).toBe("8:41 am");
    });

    it("says today, yesterday or the date", () => {
        expect(callWhen("2026-11-05T09:05:00Z", DUBLIN, NOW)).toBe("9:05 am");
        expect(callWhen("2026-11-04T18:30:00Z", DUBLIN, NOW)).toBe("Yesterday 6:30 pm");
        expect(callWhen("2026-11-02T18:30:00Z", DUBLIN, NOW)).toBe("Mon 2 Nov, 6:30 pm");
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
        expect(followUpTitle(item())).toBe("Call back +353 87 123 4567");
        expect(followUpTitle(item({ kind: "transfer_not_answered" }))).toBe("Transfer not answered");
        expect(followUpTitle(item({ kind: "repeat_caller", repeat_count: 3 }))).toBe("+353 87 123 4567 rang 3 times");
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
        ).toBe("Rang 2 times since 9:00 am and didn't reach anyone.");
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

describe("call-review follow-ups", () => {
    it("words a question the agent couldn't answer and a full time", () => {
        const question = item({ kind: "unanswered_question", questions: ["Do you have gluten-free pasta?"] });
        expect(followUpTitle(question)).toBe("Your agent couldn't answer");
        expect(followUpDetail(question, DUBLIN, NOW)).toMatch(/^“Do you have gluten-free pasta\?” Add the answer once/);
        const full = item({ kind: "time_was_full", summary: "Wanted 7:30 pm Friday for 5; offered 8:15 pm." });
        expect(followUpTitle(full)).toBe("Time was full");
        expect(followUpDetail(full, DUBLIN, NOW)).toBe("Wanted 7:30 pm Friday for 5; offered 8:15 pm.");
    });

    it("keys a follow-up by call and kind (one call can have two)", () => {
        expect(followUpKey(item({ kind: "callback" }))).not.toBe(followUpKey(item({ kind: "unanswered_question" })));
    });

    it("adds an answer as a Q/A line of its own", () => {
        expect(appendAnswer("", " Gluten-free? ", "Yes,\n just ask.")).toBe("Q: Gluten-free? A: Yes, just ask.");
        expect(appendAnswer("Parking: Henry Street.\n", "Dogs?", "On the terrace.")).toBe(
            "Parking: Henry Street.\nQ: Dogs? A: On the terrace.",
        );
    });
});

describe("afterHoursWords", () => {
    it("counts calls outside opening hours and names agents left out", () => {
        expect(afterHoursWords({ calls: 3, agents_without_hours: [] })).toEqual({
            count: "3 calls came in outside opening hours",
            note: null,
        });
        expect(afterHoursWords({ calls: 1, agents_without_hours: [{ id: 2, name: "Front desk" }] })).toEqual({
            count: "1 call came in outside opening hours",
            note: "Not counted: Front desk, with no opening hours set as times.",
        });
        expect(afterHoursWords({ calls: null, agents_without_hours: [{ id: 2, name: "Front desk" }] }).count).toBeNull();
        expect(afterHoursWords({ calls: null, agents_without_hours: [] })).toEqual({ count: null, note: null });
    });
});

describe("todayLine and hourSpan", () => {
    it("puts the range's headline counts in one line, real counts only", () => {
        const tiles = { calls: 6, handled: 4, passed_to_team: 0, callbacks_requested: 1, bookings_taken: 3 };
        expect(todayLine(tiles, "bookings taken")).toEqual([
            { value: 6, words: "calls" },
            { value: 4, words: "handled by your agent" },
            { value: 3, words: "bookings taken" },
            { value: 1, words: "asked for a call back" },
        ]);
        // No bookings wording for the business: no bookings phrase, even with a count.
        expect(todayLine(tiles, null).map((p) => p.words)).not.toContain("bookings taken");
        expect(todayLine({ ...tiles, calls: 1, handled: 1, callbacks_requested: 0, bookings_taken: 0 }, "bookings taken")).toEqual([
            { value: 1, words: "call" },
            { value: 1, words: "handled by your agent" },
        ]);
        expect(todayLine({ ...tiles, calls: 0 }, "bookings taken")).toEqual([]);
    });

    it("names an hour as a span", () => {
        expect(hourSpan(9)).toBe("09:00–10:00");
        expect(hourSpan(23)).toBe("23:00–00:00");
    });

    it("names the language a caller spoke, and marks the review kinds done on their own", () => {
        const polish = item({ kind: "other_language", caller_language: "pl", caller_language_name: "Polish", summary: null });
        expect(followUpChip(polish)).toBe("Spoke Polish");
        expect(followUpTitle(polish)).toBe("Spoke Polish");
        expect(followUpDetail(polish, DUBLIN, NOW)).toMatch(/member of staff or a call back/);
        const unknown = item({ kind: "other_language", caller_language_name: null });
        expect(followUpChip(unknown)).toBe("Spoke another language");
        const emergency = item({ kind: "emergency", summary: "Described chest pain; told to dial 112." });
        expect(followUpChip(emergency)).toBe("Emergency call");
        expect(followUpTitle(emergency)).toBe("Emergency: sent to 112/999");
        expect(followUpDetail(emergency, DUBLIN, NOW)).toBe("Described chest pain; told to dial 112.");
        expect(followUpChip(item({ kind: "callback" }))).toBe("Callback requested");
        expect(FOLLOW_UP_KINDS).toContain("other_language");
        expect(FOLLOW_UP_WORDS.other_language.filter).toBe("Spoke another language");
        expect(markKind("other_language")).toBe("other_language");
        expect(markKind("emergency")).toBe("emergency");
        expect(markKind("callback")).toBeNull();
    });
});

describe("opening hours on the hourly chart", () => {
    it("says a range the short way", () => {
        expect(openRangeWords({ start: 540, end: 1050 })).toBe("9 am–5:30 pm");
        expect(openRangeWords({ start: 720, end: 900 })).toBe("12–3 pm");
        expect(openRangeWords({ start: 1020, end: 1440 })).toBe("5 pm–midnight");
        expect(openRangeWords({ start: 0, end: 1440 })).toBe("24 hours");
        expect(openRangesWords([{ start: 720, end: 900 }, { start: 1020, end: 1320 }])).toBe("12–3 pm and 5–10 pm");
    });

    it("joins last night's late hours to tonight's", () => {
        expect(openRangesWords([{ start: 0, end: 120 }, { start: 1080, end: 1440 }])).toBe("6 pm–2 am");
    });

    const band = (kind: "none" | "differ" | "same" | "most_days", ranges: { start: number; end: number }[], days = 1) => ({
        kind,
        ranges,
        days,
        description: "Monday to Friday 9 am to 5:30 pm, closed Saturday and Sunday",
    });

    it("labels today's hours, or closed", () => {
        expect(openHoursLegend(band("same", [{ start: 540, end: 1050 }]), "today")).toEqual({
            label: "Open 9 am–5:30 pm",
            band: true,
            note: null,
        });
        expect(openHoursLegend(band("same", []), "today")?.label).toBe("Closed today");
    });

    it("over days, says every day or most days honestly", () => {
        expect(openHoursLegend(band("same", [{ start: 540, end: 1050 }], 7), "7d")?.label).toBe(
            "Open 9 am–5:30 pm every day",
        );
        const most = openHoursLegend(band("most_days", [{ start: 540, end: 1050 }], 7), "7d");
        expect(most?.label).toBe("Open 9 am–5:30 pm on most days");
        expect(most?.note).toBe("Your hours: Monday to Friday 9 am to 5:30 pm, closed Saturday and Sunday");
        expect(openHoursLegend(band("most_days", [], 30), "30d")).toMatchObject({ band: false, label: "Hours vary from day to day" });
    });

    it("draws no band when agents differ or have no hours as times", () => {
        expect(openHoursLegend(band("differ", []), "today")).toEqual({
            label: "Opening hours differ by agent",
            band: false,
            note: null,
        });
        expect(openHoursLegend(band("none", []), "today")).toBeNull();
        expect(openHoursLegend(undefined, "today")).toBeNull();
    });

    it("gives an after-hours call its day", () => {
        const now = new Date("2026-11-09T15:00:00Z");
        expect(callDayAndTime("2026-11-09T07:30:00Z", "Europe/Dublin", now)).toBe("Today 7:30 am");
        expect(callDayAndTime("2026-11-08T21:05:00Z", "Europe/Dublin", now)).toBe("Yesterday 9:05 pm");
    });
});

describe("primaryAgentId", () => {
    const agent = (id: number, active = true, phone_numbers: string[] = []) => ({
        id,
        name: `Agent ${id}`,
        active,
        phone_numbers,
    });

    it("picks the agent a number rings over an older one without", () => {
        expect(primaryAgentId({ agents: [agent(18), agent(50, true, ["7000"])] })).toBe(50);
    });

    it("falls back to the first switched-on agent, then the first", () => {
        expect(primaryAgentId({ agents: [agent(18, false), agent(50)] })).toBe(50);
        expect(primaryAgentId({ agents: [agent(18, false)] })).toBe(18);
        expect(primaryAgentId({ agents: [] })).toBeNull();
    });
});

describe("agentLineLabel", () => {
    const agent = (phone_numbers: string[]) => ({ id: 1, name: "A", active: true, phone_numbers });

    it("names the number that rings the agent", () => {
        expect(agentLineLabel(agent([]))).toBe("No phone number yet");
        expect(agentLineLabel(agent(["+353871234567"]))).toBe("Answers +353 87 123 4567");
        expect(agentLineLabel(agent(["7000", "7001"]))).toBe("Answers 7000 and 1 more");
    });
});
