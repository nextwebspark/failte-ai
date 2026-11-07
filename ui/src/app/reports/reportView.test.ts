import { describe, expect, it } from "vitest";

import { csvCell } from "./csv";
import {
    changeChip,
    estimateFormula,
    heatLevel,
    hourRange,
    money,
    mostlyWords,
    moveItem,
    reportTitle,
    shortDay,
    shortHour,
    shownCards,
    spanWords,
    tipWords,
} from "./reportView";

const card = (key: string, on = true, estimate = false) => ({
    key,
    title: key,
    size: "kpi" as const,
    estimate,
    on,
    email: false,
});

describe("reportView", () => {
    it("says hours and days the way owners do", () => {
        expect(shortHour(0)).toBe("12am");
        expect(shortHour(17)).toBe("5pm");
        expect(hourRange(17, 19)).toBe("5–7 pm");
        expect(hourRange(11, 13)).toBe("11 am–1 pm");
        expect(shortDay("2026-11-01")).toBe("Sun 1");
    });

    it("names the span in the business's zone, end exclusive", () => {
        expect(spanWords("2026-11-01T00:00:00Z", "2026-11-07T15:00:00Z", "Europe/Dublin")).toBe("1–7 Nov");
        expect(spanWords("2026-10-29T00:00:00Z", "2026-11-04T00:00:00Z", "Europe/Dublin")).toBe("29 Oct – 3 Nov");
        expect(
            reportTitle({ range: "7d", start: "2026-11-01T00:00:00Z", end: "2026-11-07T15:00:00Z", timezone: "Europe/Dublin" }),
        ).toBe("Last 7 days, 1–7 Nov");
        expect(
            reportTitle({ range: "today", start: "2026-11-07T00:00:00Z", end: "2026-11-07T15:00:00Z", timezone: "Europe/Dublin" }),
        ).toBe("Today, 7 Nov");
    });

    it("hides a change the API hid and words the rest", () => {
        expect(changeChip(null)).toBeNull();
        expect(changeChip(14)).toEqual({ tone: "up", text: "↑ 14" });
        expect(changeChip(-3)).toEqual({ tone: "down", text: "↓ 3" });
        expect(changeChip(0)?.tone).toBe("same");
    });

    it("writes the estimate's sum out", () => {
        expect(money("4970")).toBe("€4,970");
        expect(money("35.5")).toBe("€35.50");
        expect(estimateFormula(142, "cover", "35")).toBe("142 covers × your €35 average spend");
        expect(estimateFormula(1, "job", "120")).toBe("1 job × your €120 average value");
    });

    it("shows money cards only once there is an average", () => {
        const cards = [card("calls_answered"), card("bookings_value", true, true), card("covers_booked", false)];
        expect(shownCards(cards, null).map((c) => c.key)).toEqual(["calls_answered"]);
        expect(shownCards(cards, "35.00").map((c) => c.key)).toEqual(["calls_answered", "bookings_value"]);
    });

    it("moves a card and leaves out-of-range moves alone", () => {
        expect(moveItem(["a", "b", "c"], 0, 2)).toEqual(["b", "c", "a"]);
        expect(moveItem(["a", "b", "c"], 2, 1)).toEqual(["a", "c", "b"]);
        const same = ["a", "b"];
        expect(moveItem(same, 0, -1)).toBe(same);
    });

    it("shades the heatmap in five steps of one hue", () => {
        expect(heatLevel(0, 10)).toBe(0);
        expect(heatLevel(1, 10)).toBe(1);
        expect(heatLevel(10, 10)).toBe(5);
    });

    it("words the tip and the busy days", () => {
        const tip = { weekday: 4, start_hour: 17, end_hour: 19, one_in: 6 };
        expect(tipWords(tip, 7)).toBe(
            "Friday 5–7 pm takes 1 in 6 of your calls. Worth having someone free to answer transfers then.",
        );
        expect(tipWords(tip, 30).startsWith("Fridays 5–7 pm")).toBe(true);
        expect(mostlyWords([4, 5], 20)).toBe("Mostly Fri and Sat, 8–9 pm");
        expect(mostlyWords([], null)).toBeNull();
    });

    it("keeps formulas out of the download", () => {
        expect(csvCell('+353 1 "main"')).toBe('"+353 1 ""main"""');
        expect(csvCell("=HYPERLINK()")).toBe("\"'=HYPERLINK()\"");
    });
});
