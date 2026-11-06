import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BookingRulesEditor, describePeriod, problems, summarize } from "./BookingRules";

describe("booking rules helpers", () => {
    it("summarises the rules in plain words", () => {
        expect(summarize({})).toBe("One booking at a time · 30 min each · up to 14 days ahead");
        expect(summarize({ max_bookings_at_once: 5, booking_minutes: 90, max_party_size: 8, horizon_days: 30 })).toBe(
            "5 bookings at the same time · 90 min each · groups up to 8 · up to 30 days ahead",
        );
    });

    it("describes opening times", () => {
        expect(describePeriod({ days: [3, 4, 5], first_start: "17:00", last_start: "21:00" })).toBe(
            "Thu–Sat, first booking 17:00, last 21:00",
        );
        expect(describePeriod({ days: [0, 2], first_start: "09:00", last_start: "12:00" })).toBe(
            "Mon, Wed, first booking 09:00, last 12:00",
        );
    });

    it("catches mistakes before saving", () => {
        expect(problems({ service_periods: [{ days: [], first_start: "21:00", last_start: "17:00" }] })).toEqual([
            "Opening times 1: pick at least one day.",
            "Opening times 1: the first booking is after the last.",
        ]);
        expect(problems({ max_party_size: 12, max_guests_at_once: 10 })).toHaveLength(1);
        expect(problems({ max_bookings_at_once: 5 })).toEqual([]);
    });
});

describe("BookingRulesEditor", () => {
    it("starts from a preset and saves what the owner adjusts", () => {
        const onSave = vi.fn();
        render(<BookingRulesEditor initial={{}} saving={false} onSave={onSave} />);

        fireEvent.click(screen.getByRole("button", { name: "Restaurant tables" }));
        fireEvent.change(screen.getByLabelText("Bookings at the same time"), { target: { value: "8" } });
        // Close on Mondays for dinner: untick Monday in the second opening times.
        const dinner = screen.getByRole("group", { name: "Days for opening times 2" });
        fireEvent.click(dinner.querySelector("button[aria-pressed='true']") as HTMLElement);
        fireEvent.click(screen.getByRole("button", { name: "Save booking rules" }));

        const saved = onSave.mock.calls[0][0];
        expect(saved.max_bookings_at_once).toBe(8);
        expect(saved.booking_minutes).toBe(90);
        expect(saved.service_periods[1].days).toEqual([2, 3, 4, 5, 6]);
    });

    it("won't save rules with a mistake", () => {
        render(
            <BookingRulesEditor
                initial={{ service_periods: [{ days: [1], first_start: "21:00", last_start: "17:00" }] }}
                saving={false}
                onSave={vi.fn()}
            />,
        );
        expect(screen.getByRole("alert").textContent).toContain("the first booking is after the last");
        expect(screen.getByRole("button", { name: "Save booking rules" }).hasAttribute("disabled")).toBe(true);
    });
});
