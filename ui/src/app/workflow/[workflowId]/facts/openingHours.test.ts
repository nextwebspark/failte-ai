import { describe, expect, it } from "vitest";

import {
    dayChips,
    describeOpeningHours,
    forSave,
    nextRange,
    type OpeningHours,
    openingHoursProblem,
    rangeLabel,
    sameOpeningHours,
} from "./openingHours";

const LUNCH_DINNER = [
    { open: "12:00", close: "15:00" },
    { open: "17:00", close: "22:00" },
];

function week(days: { open: string; close: string }[][], extra: Partial<OpeningHours> = {}): OpeningHours {
    return { days, timezone: "Europe/Dublin", transfer_only_when_open: true, note: null, ...extra } as OpeningHours;
}

const RESTAURANT = week([[], ...Array(6).fill(LUNCH_DINNER)]);

describe("opening hours", () => {
    it("says the hours as the server does", () => {
        expect(describeOpeningHours(RESTAURANT)).toBe("Tuesday to Sunday 12 to 3 pm and 5 to 10 pm, closed Monday");
        const dental = week(
            [
                ...Array(4).fill([{ open: "08:30", close: "18:00" }]),
                [{ open: "08:30", close: "16:00" }],
                [{ open: "09:00", close: "13:00" }],
                [],
            ],
            { note: "closed on bank holidays." },
        );
        expect(describeOpeningHours(dental)).toBe(
            "Monday to Thursday 8:30 am to 6 pm, Friday 8:30 am to 4 pm, Saturday 9 am to 1 pm, closed Sunday. Closed on bank holidays.",
        );
        const late = week([[], [], [], [], [{ open: "18:00", close: "02:00" }], [{ open: "18:00", close: "02:00" }], []]);
        expect(describeOpeningHours(late)).toBe("Friday and Saturday 6 pm to 2 am, closed Monday to Thursday and Sunday");
        expect(describeOpeningHours(week(Array(7).fill([{ open: "00:00", close: "00:00" }])))).toBe("Every day open 24 hours");
        expect(describeOpeningHours(week(Array(7).fill([])))).toBe("Closed every day");
    });

    it("makes the mock's day chips", () => {
        const chips = dayChips(RESTAURANT);
        expect(chips[0]).toEqual({ short: "Mon", long: "Monday", lines: null });
        expect(chips[1].lines).toEqual(["12–3 pm", "5–10 pm"]);
        expect(rangeLabel({ open: "08:30", close: "18:00" })).toBe("8:30 am–6 pm");
        expect(rangeLabel({ open: "18:00", close: "02:00" })).toBe("6 pm–2 am");
        expect(rangeLabel({ open: "17:00", close: "00:00" })).toBe("5 pm–midnight");
        expect(rangeLabel({ open: "12:00", close: "23:00" })).toBe("12–11 pm");
    });

    it("finds what the server would refuse", () => {
        expect(openingHoursProblem(RESTAURANT)).toBeNull();
        const overlap = week([[{ open: "12:00", close: "15:00" }, { open: "14:00", close: "18:00" }], [], [], [], [], [], []]);
        expect(openingHoursProblem(overlap)).toMatch(/Monday: the opening times overlap/);
        const touching = week([[{ open: "12:00", close: "15:00" }, { open: "15:00", close: "18:00" }], [], [], [], [], [], []]);
        expect(openingHoursProblem(touching)).toMatch(/overlap/);
        const overnightFirst = week([[], [{ open: "20:00", close: "02:00" }, { open: "03:00", close: "04:00" }], [], [], [], [], []]);
        expect(openingHoursProblem(overnightFirst)).toMatch(/Tuesday: only the last/);
    });

    it("suggests the next opening time, and none when the day is full", () => {
        expect(nextRange([])).toEqual({ open: "09:00", close: "17:00" });
        expect(nextRange([{ open: "12:00", close: "15:00" }])).toEqual({ open: "16:00", close: "19:00" });
        expect(nextRange([{ open: "18:00", close: "23:30" }])).toBeNull();
    });

    it("compares and cleans for saving", () => {
        expect(sameOpeningHours(null, null)).toBe(true);
        expect(sameOpeningHours(RESTAURANT, null)).toBe(false);
        expect(sameOpeningHours(RESTAURANT, week([[], ...Array(6).fill(LUNCH_DINNER)]))).toBe(true);
        expect(sameOpeningHours(RESTAURANT, { ...RESTAURANT, transfer_only_when_open: false })).toBe(false);
        expect(forSave({ ...RESTAURANT, note: "  " }).note).toBeNull();
    });
});
