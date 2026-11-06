import { describe, expect, it } from "vitest";

import {
    callDetails,
    callerNameOf,
    callOutcome,
    callsQueryFromParams,
    callsQueryToParams,
    chipFilters,
    dateRangeFor,
    DEFAULT_QUERY,
    formatCallTime,
    formatCallWhen,
    formatDuration,
    formatLength,
    formatLengthWords,
    formatPhone,
    outcomeLabel,
    pageList,
    tabFilter,
    whatHappened,
    whenLabel,
} from "./callsView";

const NOW = new Date(2026, 10, 6, 15, 0);

describe("the URL", () => {
    it("reads the everyday view from a bare /usage", () => {
        expect(callsQueryFromParams(new URLSearchParams())).toEqual(DEFAULT_QUERY);
        expect(DEFAULT_QUERY.when).toBe("7d");
    });

    it("round-trips every control and leaves defaults out", () => {
        const query = {
            ...DEFAULT_QUERY,
            tab: "team" as const,
            q: "Murphy",
            when: "custom" as const,
            start: "2026-11-01",
            end: "2026-11-03",
            outcome: "callback_requested",
            who: "agent" as const,
            page: 3,
        };
        const params = callsQueryToParams(query, { filters: "[]", call: 42 });
        expect(params.get("call")).toBe("42");
        expect(params.get("filters")).toBe("[]");
        expect(callsQueryFromParams(params)).toEqual(query);
        expect(callsQueryToParams(DEFAULT_QUERY).toString()).toBe("");
    });

    it("ignores values it can't read", () => {
        const query = callsQueryFromParams(new URLSearchParams("tab=nope&when=custom&start=soon&who=boss&page=-2"));
        expect(query).toEqual(DEFAULT_QUERY);
    });
});

describe("dates", () => {
    it("turns presets into local day ranges", () => {
        const week = dateRangeFor({ when: "7d", start: null, end: null }, NOW)!;
        expect(week.from).toEqual(new Date(2026, 9, 31));
        expect(week.to.getDate()).toBe(6);
        expect(dateRangeFor({ when: "all", start: null, end: null }, NOW)).toBeNull();
    });

    it("reads a custom range either way round", () => {
        const range = dateRangeFor({ when: "custom", start: "2026-11-03", end: "2026-11-01" }, NOW)!;
        expect(range.from).toEqual(new Date(2026, 10, 1));
        expect(range.to.getDate()).toBe(3);
    });

    it("labels the chip", () => {
        expect(whenLabel({ when: "7d", start: null, end: null })).toBe("Last 7 days");
        expect(whenLabel({ when: "custom", start: "2026-11-01", end: "2026-11-03" })).toBe("1 Nov – 3 Nov");
        expect(whenLabel({ when: "custom", start: "2026-11-01", end: null })).toBe("1 Nov");
    });
});

describe("filters", () => {
    it("gives each tab a filter the API can count", () => {
        expect(tabFilter("all")).toBeNull();
        expect(tabFilter("bookings")?.attribute).toBe("bookingOutcome");
        expect(tabFilter("team")).toEqual({ attribute: "handledBy", type: "radio", value: { status: "team" } });
    });

    it("sends the search, outcome and who-handled-it chips", () => {
        expect(chipFilters({ q: "  087 1 ", outcome: "XFER", who: "team" })).toEqual([
            { attribute: "callerSearch", type: "text", value: { value: "087 1" } },
            { attribute: "dispositionCode", type: "multiSelect", value: { codes: ["XFER"] } },
            { attribute: "handledBy", type: "radio", value: { status: "team" } },
        ]);
        expect(chipFilters({ q: " ", outcome: null, who: null })).toEqual([]);
    });
});

const GATHERED = {
    caller_name: "Declan Murphy",
    call_reason: "",
    mapped_call_disposition: "end_call",
    call_tags: ["end_call", "user_speech"],
    extracted_variables: {
        caller_name: "Declan Murphy",
        callback_number: "+353875511234",
        call_reason: "",
        booking_outcome: "booked",
        booking_date: "2026-11-14",
        booking_time: "19:00",
        party_size: "4",
        special_requests: "",
        tag_vip: "yes",
    },
};

describe("one call in plain words", () => {
    it("reads the caller's name", () => {
        expect(callerNameOf(GATHERED)).toBe("Declan Murphy");
        expect(callerNameOf({ caller_name: " " })).toBeNull();
        expect(callerNameOf(null)).toBeNull();
    });

    it("lists the details the agent took, labelled plainly", () => {
        expect(callDetails(GATHERED)).toEqual([
            { key: "caller_name", label: "Name", value: "Declan Murphy" },
            { key: "callback_number", label: "Number to call back", value: "+353 87 551 1234" },
            { key: "booking_outcome", label: "Booking", value: "Booked" },
            { key: "booking_date", label: "Date", value: "Sat 14 Nov" },
            { key: "booking_time", label: "Time", value: "7:00 pm" },
            { key: "party_size", label: "Party size", value: "4" },
        ]);
        expect(callDetails({ extracted_variables: { loyalty_card: "Gold" } })).toEqual([
            { key: "loyalty_card", label: "Loyalty card", value: "Gold" },
        ]);
    });

    it("says what happened only from what was taken down", () => {
        expect(whatHappened(GATHERED)).toBe("Booking made · Sat 14 Nov, 7:00 pm · 4 people");
        expect(whatHappened({ extracted_variables: { call_reason: "Asked about parking" } })).toBe("Asked about parking");
        expect(whatHappened({ extracted_variables: { call_reason: "" } })).toBeNull();
        expect(whatHappened(null)).toBeNull();
    });

    it("words the outcome", () => {
        expect(callOutcome({ disposition: "callback_requested", gathered_context: {} })).toEqual({
            label: "Callback requested",
            tone: "warn",
        });
        expect(callOutcome({ disposition: "end_call", gathered_context: { call_status: "transfer_call" } }).label).toBe(
            "Passed to your team",
        );
        expect(
            callOutcome({ disposition: "user_hangup", gathered_context: { call_tags: ["user_hangup"] } }).label,
        ).toBe("Hung up without speaking");
        expect(
            callOutcome({ disposition: "user_hangup", gathered_context: { call_tags: ["user_hangup", "user_speech"] } })
                .label,
        ).toBe("Caller hung up");
        expect(callOutcome({ disposition: null, gathered_context: null }).label).toBe("Not recorded");
    });

    it("formats an Irish mobile number", () => {
        expect(formatPhone("+353871234567")).toBe("+353 87 123 4567");
        expect(formatPhone("+14155550100")).toBe("+14155550100");
    });
});

describe("labels", () => {
    it("reads outcome codes as words", () => {
        expect(outcomeLabel("callback_requested")).toBe("Callback requested");
        expect(outcomeLabel("no-answer")).toBe("No answer");
        expect(outcomeLabel("transfer_call")).toBe("Passed to your team");
        expect(outcomeLabel("XFER")).toBe("XFER");
        expect(outcomeLabel("INFO_GIVEN")).toBe("Info given");
    });

    it("formats call length", () => {
        expect(formatDuration(45)).toBe("45s");
        expect(formatDuration(185)).toBe("3m 5s");
        expect(formatLength(132)).toBe("2:12");
        expect(formatLength(4)).toBe("0:04");
        expect(formatLengthWords(132)).toBe("2 min 12 s");
        expect(formatLengthWords(45)).toBe("45 s");
    });
});

describe("formatCallWhen", () => {
    const now = new Date("2026-11-06T15:00:00Z");

    it("says today and yesterday, Irish style, in the workspace's zone", () => {
        expect(formatCallWhen("2026-11-06T13:41:00Z", "Europe/Dublin", now)).toBe("Today 1:41 pm");
        expect(formatCallWhen("2026-11-05T21:12:00Z", "Europe/Dublin", now)).toBe("Yesterday 9:12 pm");
        expect(formatCallWhen("2026-11-02T00:05:00Z", "Europe/Dublin", now)).toBe("Mon 2 Nov, 12:05 am");
        expect(formatCallWhen("2025-11-03T12:00:00Z", "Europe/Dublin", now)).toBe("3 Nov 2025, 12:00 pm");
    });

    it("uses the zone's day, not the browser's", () => {
        // 12:30 in Dublin today was 23:30 yesterday in Sydney, where it's already the 7th.
        expect(formatCallWhen("2026-11-06T12:30:00Z", "Europe/Dublin", now)).toBe("Today 12:30 pm");
        expect(formatCallWhen("2026-11-06T12:30:00Z", "Australia/Sydney", now)).toBe("Yesterday 11:30 pm");
    });
});

describe("formatCallTime", () => {
    it("reads Irish-style in the workspace's zone, with a 24-hour clock", () => {
        expect(formatCallTime("2026-07-06T12:12:00Z", "Europe/Dublin")).toBe("Mon 6 Jul 2026, 13:12");
    });

    it("survives an unknown zone name", () => {
        expect(formatCallTime("2026-11-06T13:12:00Z", "Not/AZone")).toMatch(/6 Nov 2026/);
    });
});

describe("pageList", () => {
    it("shows every page when there are few", () => {
        expect(pageList(1, 3)).toEqual([1, 2, 3]);
    });

    it("keeps the ends and the pages around the current one", () => {
        expect(pageList(1, 32)).toEqual([1, 2, 3, 4, "gap", 32]);
        expect(pageList(16, 32)).toEqual([1, "gap", 15, 16, 17, "gap", 32]);
        expect(pageList(32, 32)).toEqual([1, "gap", 29, 30, 31, 32]);
    });
});
