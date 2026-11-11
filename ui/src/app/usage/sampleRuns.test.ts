import { describe, expect, it } from "vitest";

import { sampleCalls } from "@/lib/sampleData";

import { callerNameOf, callOutcome, callSummary, DEFAULT_QUERY } from "./callsView";
import { filterSampleRuns, isSampleRun, sampleOutcomeCodes, sampleRuns, sampleTabCounts, searchDigits } from "./sampleRuns";

const NOW = new Date(2026, 10, 6, 15, 0);
const RUNS = sampleRuns("Trattoria Bella", NOW);

describe("sample calls as list rows", () => {
    it("shapes every sample call like a row, newest first", () => {
        expect(RUNS).toHaveLength(sampleCalls().length);
        expect(RUNS.every((run) => isSampleRun(run) && run.sample)).toBe(true);
        const times = RUNS.map((run) => run.created_at);
        expect([...times].sort().reverse()).toEqual(times);
        const declan = RUNS.find((run) => run.id === -1)!;
        expect(callerNameOf(declan.gathered_context)).toBe("Declan Murphy");
        expect(callSummary(declan)).toMatch(/^Booked a table for 4/);
        expect(callOutcome(declan).label).toBe("Booking made");
        expect(declan.reason_label).toBe("Reservations");
        expect(declan.recording_url).toBeUndefined();
        expect(declan.sample?.transcript[0].text).toContain("Trattoria Bella");
    });

    it("counts the tabs from the sample", () => {
        const counts = sampleTabCounts(RUNS, DEFAULT_QUERY, NOW);
        expect(counts).toEqual({ all: 11, follow_up: 4, bookings: 3, team: 1 });
    });

    it("searches names, numbers, the summary and what was said", () => {
        const search = (q: string) => filterSampleRuns(RUNS, { ...DEFAULT_QUERY, q }, "all", NOW).map((run) => run.id);
        expect(search("murphy")).toEqual([-1]);
        expect(search("087 551")).toEqual([-1]);
        expect(search("gluten")).toEqual([-9]);
        expect(search("half seven")).toEqual([-4]);
        expect(search("zzz")).toEqual([]);
    });

    it("applies the chips and the date the same way as the API", () => {
        const filter = (change: Partial<typeof DEFAULT_QUERY>) =>
            filterSampleRuns(RUNS, { ...DEFAULT_QUERY, ...change }, "all", NOW).length;
        expect(filter({ who: "team" })).toBe(1);
        expect(filter({ who: "agent" })).toBe(10);
        expect(filter({ outcome: "booking_made" })).toBe(2);
        expect(filter({ when: "today" })).toBeLessThan(11);
        expect(sampleOutcomeCodes(RUNS)).toContain("time_was_full");
    });

    it("reads numbers as the server does", () => {
        expect(searchDigits("087 551")).toBe("87551");
        expect(searchDigits("0035387")).toBe("35387");
        expect(searchDigits("Murphy")).toBe("");
    });
});
