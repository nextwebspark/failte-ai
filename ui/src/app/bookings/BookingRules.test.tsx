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

    it("refuses numbers that are not whole, or too small", () => {
        const onSave = vi.fn();
        render(<BookingRulesEditor initial={{}} saving={false} onSave={onSave} />);
        const save = () => screen.getByRole("button", { name: "Save booking rules" });

        fireEvent.change(screen.getByLabelText("Bookings at the same time"), { target: { value: "0" } });
        expect(screen.getByRole("alert").textContent).toContain("Bookings at the same time: use a whole number, 1 or more.");
        expect(save().hasAttribute("disabled")).toBe(true);

        fireEvent.change(screen.getByLabelText("Bookings at the same time"), { target: { value: "2.5" } });
        expect(screen.getByRole("alert").textContent).toContain("whole number");

        fireEvent.change(screen.getByLabelText("Bookings at the same time"), { target: { value: "2" } });
        expect(screen.queryByRole("alert")).toBeNull();
        fireEvent.click(save());
        expect(onSave).toHaveBeenCalledTimes(1);
        expect(onSave.mock.calls[0][0].max_bookings_at_once).toBe(2);
    });

    it("allows 0 for reset time and notice but not below", () => {
        render(<BookingRulesEditor initial={{}} saving={false} onSave={vi.fn()} />);

        fireEvent.change(screen.getByLabelText("Reset time between bookings (minutes)"), { target: { value: "0" } });
        fireEvent.change(screen.getByLabelText("Minimum notice (hours)"), { target: { value: "0" } });
        expect(screen.queryByRole("alert")).toBeNull();

        fireEvent.change(screen.getByLabelText("Minimum notice (hours)"), { target: { value: "-1" } });
        expect(screen.getByRole("alert").textContent).toContain("Minimum notice (hours): use a whole number, 0 or more.");
    });

    it("clearing a number goes back to the default", () => {
        const onSave = vi.fn();
        render(<BookingRulesEditor initial={{ horizon_days: 30 }} saving={false} onSave={onSave} />);
        fireEvent.change(screen.getByLabelText("Book up to (days ahead)"), { target: { value: "" } });
        fireEvent.click(screen.getByRole("button", { name: "Save booking rules" }));
        expect(onSave.mock.calls[0][0].horizon_days).toBeUndefined();
    });

    it("removes an opening time", () => {
        const onSave = vi.fn();
        render(
            <BookingRulesEditor
                initial={{
                    service_periods: [
                        { days: [0], first_start: "09:00", last_start: "12:00" },
                        { days: [1], first_start: "13:00", last_start: "17:00" },
                    ],
                }}
                saving={false}
                onSave={onSave}
            />,
        );
        fireEvent.click(screen.getByRole("button", { name: "Remove opening times 1" }));
        expect(screen.queryByRole("group", { name: "Days for opening times 2" })).toBeNull();
        fireEvent.click(screen.getByRole("button", { name: "Save booking rules" }));
        expect(onSave.mock.calls[0][0].service_periods).toEqual([{ days: [1], first_start: "13:00", last_start: "17:00" }]);
    });

    it("removing the last opening time shows the default hours", () => {
        render(
            <BookingRulesEditor
                initial={{ service_periods: [{ days: [0], first_start: "09:00", last_start: "12:00" }] }}
                saving={false}
                onSave={vi.fn()}
            />,
        );
        fireEvent.click(screen.getByRole("button", { name: "Remove opening times 1" }));
        expect(screen.getByText("Weekdays, 9am to 5pm (the default).")).toBeTruthy();
    });

    it("a preset replaces what was typed", () => {
        const onSave = vi.fn();
        render(<BookingRulesEditor initial={{ max_party_size: 3, horizon_days: 60 }} saving={false} onSave={onSave} />);
        fireEvent.click(screen.getByRole("button", { name: "Appointments" }));
        fireEvent.click(screen.getByRole("button", { name: "Save booking rules" }));
        const saved = onSave.mock.calls[0][0];
        expect(saved.max_party_size).toBeUndefined();
        expect(saved.horizon_days).toBe(14);
        expect(saved.max_bookings_at_once).toBe(1);
    });

    it("shows each preset's help as text and links it to the button", () => {
        render(<BookingRulesEditor idPrefix="cal-a" initial={{}} saving={false} onSave={vi.fn()} />);
        const help = screen.getByText(/One booking at a time, e.g. a clinic/);
        const button = screen.getByRole("button", { name: "Appointments" });
        expect(button.getAttribute("aria-describedby")).toBe(help.id);
        expect(button.getAttribute("title")).toBeNull();
    });

    it("keeps input ids unique when two calendars show the editor", () => {
        const { container } = render(
            <>
                <BookingRulesEditor idPrefix="cal-a" initial={{}} saving={false} onSave={vi.fn()} />
                <BookingRulesEditor idPrefix="cal-b" initial={{}} saving={false} onSave={vi.fn()} />
            </>,
        );
        const ids = Array.from(container.querySelectorAll("[id]")).map((el) => el.id);
        expect(new Set(ids).size).toBe(ids.length);
        expect(screen.getAllByLabelText("Bookings at the same time")).toHaveLength(2);
    });

    it("keeps days in order when a day is ticked again", () => {
        const onSave = vi.fn();
        render(
            <BookingRulesEditor
                initial={{ service_periods: [{ days: [0, 4], first_start: "09:00", last_start: "12:00" }] }}
                saving={false}
                onSave={onSave}
            />,
        );
        const days = screen.getByRole("group", { name: "Days for opening times 1" });
        fireEvent.click(days.querySelectorAll("button")[2]);
        fireEvent.click(screen.getByRole("button", { name: "Save booking rules" }));
        expect(onSave.mock.calls[0][0].service_periods[0].days).toEqual([0, 2, 4]);
    });

    it("can't save while saving", () => {
        render(<BookingRulesEditor initial={{}} saving onSave={vi.fn()} />);
        expect(screen.getByRole("button", { name: "Saving…" }).hasAttribute("disabled")).toBe(true);
    });
});

describe("problems() numbers", () => {
    it("flags non-integers and values under the minimum", () => {
        expect(problems({ slot_minutes: 0 })).toEqual(["Gap between start times (minutes): use a whole number, 1 or more."]);
        expect(problems({ buffer_minutes: -5 })).toEqual(["Reset time between bookings (minutes): use a whole number, 0 or more."]);
        expect(problems({ horizon_days: 1.5 })).toHaveLength(1);
        expect(problems({ booking_minutes: Number.NaN })).toHaveLength(1);
        expect(problems({ buffer_minutes: 0, min_lead_hours: 0, slot_minutes: 1 })).toEqual([]);
    });
});
