import { describe, expect, it } from "vitest";

import type { CalendarBooking } from "@/client/types.gen";

import { groupByDay, isoWithOffset, partyLabel, rangeFor, timeRange, totals } from "./bookingsView";

const NOW = new Date(2026, 9, 15, 10, 30); // Thursday 15 October, local time

function booking(day: number, hour: number, overrides: Partial<CalendarBooking> = {}): CalendarBooking {
    const start = new Date(2026, 9, day, hour, 0);
    return {
        event_id: `evt-${day}-${hour}`,
        connection_id: "c1",
        start: start.toISOString(),
        end: new Date(start.getTime() + 90 * 60_000).toISOString(),
        status: "confirmed",
        caller_name: "Mary Byrne",
        party_size: 4,
        ...overrides,
    };
}

describe("rangeFor", () => {
    it("starts today for upcoming ranges and ends today for the past week", () => {
        expect(rangeFor("next7", NOW)).toEqual({ start: new Date(2026, 9, 15), end: new Date(2026, 9, 22) });
        expect(rangeFor("next14", NOW).end).toEqual(new Date(2026, 9, 29));
        expect(rangeFor("past7", NOW)).toEqual({ start: new Date(2026, 9, 8), end: new Date(2026, 9, 15) });
    });

    it("sends the browser's offset", () => {
        expect(isoWithOffset(new Date(2026, 9, 15))).toMatch(/^2026-10-15T00:00:00([+-]\d{2}:\d{2}|Z)$/);
    });
});

describe("groupByDay", () => {
    const list = [
        booking(15, 19),
        booking(15, 20, { party_size: 2, status: "cancelled" }),
        booking(16, 18, { party_size: null }),
        booking(19, 13, { party_size: 6 }),
    ];

    it("labels today and tomorrow and counts confirmed guests", () => {
        const groups = groupByDay(list, NOW, true);
        expect(groups.map((g) => g.label)).toEqual([
            "Today · Thu 15 Oct",
            "Tomorrow · Fri 16 Oct",
            "Monday 19 October",
        ]);
        expect(groups[0]).toMatchObject({ confirmed: 1, guests: 4 });
        expect(groups[0].bookings).toHaveLength(2);
        expect(groups[1]).toMatchObject({ confirmed: 1, guests: 0 });
    });

    it("hides cancelled bookings unless asked", () => {
        const groups = groupByDay(list, NOW, false);
        expect(groups[0].bookings.map((b) => b.status)).toEqual(["confirmed"]);
    });
});

describe("labels", () => {
    it("says Not asked when the agent took no party size", () => {
        expect(partyLabel({ party_size: null })).toBe("Not asked");
        expect(partyLabel({ party_size: undefined })).toBe("Not asked");
        expect(partyLabel({ party_size: 1 })).toBe("1 guest");
        expect(partyLabel({ party_size: 6 })).toBe("6 guests");
    });

    it("shows local start and end times", () => {
        expect(timeRange(booking(15, 19))).toBe("19:00–20:30");
    });

    it("totals confirmed, cancelled, guests and bookings without a party size", () => {
        expect(
            totals([
                booking(15, 19),
                booking(15, 20, { status: "cancelled" }),
                booking(16, 18, { party_size: null }),
            ]),
        ).toEqual({ confirmed: 2, cancelled: 1, guests: 4, noPartySize: 1 });
    });
});
