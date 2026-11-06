import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BookingListResponse } from "@/client/types.gen";

import BookingsPage from "./page";

const mocks = vi.hoisted(() => ({
    list: vi.fn(),
    update: vi.fn(),
    can: vi.fn<(...permissions: string[]) => boolean>(() => true),
    role: "admin" as string | null,
}));

vi.stubGlobal(
    "ResizeObserver",
    class {
        observe() {}
        unobserve() {}
        disconnect() {}
    },
);

vi.mock("@/client/sdk.gen", () => ({
    listBookingsApiV1IntegrationsBookingsGet: mocks.list,
    setAiBookingApiV1IntegrationsBookingsCalendarsConnectionIdPut: mocks.update,
}));

vi.mock("@/context/OrgConfigContext", () => ({
    useOrgConfig: () => ({ can: mocks.can, role: mocks.role, loading: false }),
}));

vi.mock("sonner", () => ({
    toast: { success: vi.fn(), error: vi.fn() },
}));

const CAL = "4f1c2d3e-5a6b-4c7d-8e9f-0a1b2c3d4e5f";

function at(daysFromToday: number, hour: number): string {
    const d = new Date();
    d.setHours(hour, 0, 0, 0);
    d.setDate(d.getDate() + daysFromToday);
    return d.toISOString();
}

function listing(overrides: Partial<BookingListResponse> = {}): BookingListResponse {
    return {
        calendars: [
            {
                connection_id: CAL,
                provider: "google-calendar",
                title: "Google Calendar",
                account_label: "Dinner bookings",
                ai_booking_enabled: true,
                ok: true,
            },
        ],
        bookings: [
            {
                event_id: "e1",
                connection_id: CAL,
                start: at(0, 19),
                end: at(0, 20),
                status: "confirmed",
                caller_name: "Mary Byrne",
                caller_phone: "087 123 4567",
                party_size: 4,
                reason: "Birthday",
            },
            {
                event_id: "e2",
                connection_id: CAL,
                start: at(1, 18),
                end: at(1, 19),
                status: "confirmed",
                caller_name: "Sean Kelly",
                party_size: null,
            },
            {
                event_id: "e3",
                connection_id: CAL,
                start: at(1, 20),
                end: at(1, 21),
                status: "cancelled",
                caller_name: "Aoife Ryan",
                party_size: 2,
            },
        ],
        ...overrides,
    };
}

describe("BookingsPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.can.mockImplementation(() => true);
        mocks.role = "admin";
        mocks.list.mockResolvedValue({ data: listing() });
        mocks.update.mockResolvedValue({ data: {} });
    });

    it("lists bookings by day with the party size, or Not asked", async () => {
        render(<BookingsPage />);

        expect(await screen.findByText("Mary Byrne")).toBeTruthy();
        expect(screen.getByText("4 guests")).toBeTruthy();
        expect(screen.getByText("Not asked")).toBeTruthy();
        expect(screen.getByText(/^Today ·/)).toBeTruthy();
        expect(screen.getByText(/^Tomorrow ·/)).toBeTruthy();
        expect(screen.getByRole("link", { name: /087 123 4567/ }).getAttribute("href")).toBe("tel:0871234567");
        // Cancelled bookings stay hidden until asked for.
        expect(screen.queryByText("Aoife Ryan")).toBeNull();
        expect(screen.getByText(/2 bookings · 4 guests · 1 without a party size · 1 cancelled/)).toBeTruthy();

        fireEvent.click(screen.getByRole("switch", { name: "Show cancelled" }));
        expect(screen.getByText("Aoife Ryan")).toBeTruthy();
        expect(screen.getByText("Cancelled")).toBeTruthy();
    });

    it("asks the API for the chosen range with offsets", async () => {
        render(<BookingsPage />);
        await screen.findByText("Mary Byrne");

        fireEvent.click(screen.getByRole("button", { name: "Last 7 days" }));

        await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
        const { start, end } = mocks.list.mock.calls[1][0].query;
        expect(start).toMatch(/T00:00:00([+-]\d{2}:\d{2}|Z)$/);
        expect(new Date(end).getTime() - new Date(start).getTime()).toBeGreaterThanOrEqual(6.9 * 86_400_000);
    });

    it("lets an admin switch AI booking off for a calendar", async () => {
        render(<BookingsPage />);
        const toggle = await screen.findByRole("switch", { name: "Let the agent book" });

        fireEvent.click(toggle);

        await waitFor(() =>
            expect(mocks.update).toHaveBeenCalledWith({
                path: { connection_id: CAL },
                body: { ai_booking_enabled: false },
            }),
        );
        expect(await screen.findByText("Booking off")).toBeTruthy();
        expect(screen.getByText(/won't book on this calendar/)).toBeTruthy();
        expect(toast.success).toHaveBeenCalled();
    });

    it("lets the owner allow cancelling and moving after checking the caller", async () => {
        render(<BookingsPage />);
        const toggle = await screen.findByRole("switch", { name: "Let the agent cancel or move bookings" });
        expect(toggle.getAttribute("aria-checked")).toBe("false");
        expect(screen.getByText(/phone number the booking was made under/)).toBeTruthy();

        fireEvent.click(toggle);

        await waitFor(() =>
            expect(mocks.update).toHaveBeenCalledWith({
                path: { connection_id: CAL },
                body: { ai_changes_enabled: true },
            }),
        );
        await waitFor(() => expect(toggle.getAttribute("aria-checked")).toBe("true"));
    });

    it("shows staff the bookings but not the switch, unless allowed", async () => {
        mocks.can.mockImplementation((...perms: string[]) => perms.every((p) => p === "calls:read"));
        render(<BookingsPage />);

        expect(await screen.findByText("Mary Byrne")).toBeTruthy();
        expect(screen.queryByRole("switch", { name: "Let the agent book" })).toBeNull();
        expect(screen.getByText("Agent books")).toBeTruthy();
    });

    it("explains how to connect a calendar when there is none", async () => {
        mocks.list.mockResolvedValue({ data: { calendars: [], bookings: [] } });
        render(<BookingsPage />);

        expect(await screen.findByText("No calendar connected yet")).toBeTruthy();
        expect(screen.getByRole("link", { name: "Connect a calendar" }).getAttribute("href")).toBe("/integrations");
    });

    it("reports a calendar that cannot be read", async () => {
        mocks.list.mockResolvedValue({
            data: listing({
                calendars: [
                    {
                        connection_id: CAL,
                        provider: "google-calendar",
                        title: "Google Calendar",
                        account_label: null,
                        ai_booking_enabled: true,
                        ok: false,
                        error: "the calendar was not found; make sure it is shared with bot@x",
                    },
                ],
                bookings: [],
            }),
        });
        render(<BookingsPage />);

        expect(await screen.findByText(/Couldn't read this calendar: the calendar was not found/)).toBeTruthy();
        expect(screen.getByRole("link", { name: "Check the connection" })).toBeTruthy();
    });

    it("refuses roles that cannot see calls", () => {
        mocks.can.mockImplementation(() => false);
        render(<BookingsPage />);
        expect(mocks.list).not.toHaveBeenCalled();
    });

    it("only offers to connect a calendar to people who can change integrations", async () => {
        mocks.list.mockResolvedValue({ data: { calendars: [], bookings: [] } });
        // The owner can manage bookings but not integrations.
        mocks.can.mockImplementation((...perms: string[]) =>
            perms.every((p) => ["calls:read", "bookings:manage"].includes(p)),
        );
        render(<BookingsPage />);

        expect(await screen.findByText("No calendar connected yet")).toBeTruthy();
        expect(screen.queryByRole("link", { name: "Connect a calendar" })).toBeNull();
        expect(screen.getByText(/Ask an admin on your team to connect your calendar/)).toBeTruthy();
    });

    it("explains a calendar read error in plain words to people who can't see Integrations", async () => {
        mocks.can.mockImplementation((...perms: string[]) => perms.every((p) => p === "calls:read"));
        mocks.list.mockResolvedValue({
            data: listing({
                calendars: [
                    {
                        connection_id: CAL,
                        provider: "google-calendar",
                        title: "Google Calendar",
                        account_label: null,
                        ai_booking_enabled: true,
                        ok: false,
                        error: "HttpError 404 calendarId not found",
                    },
                ],
                bookings: [],
            }),
        });
        render(<BookingsPage />);

        const alert = await screen.findByText(/We couldn't read this calendar/);
        expect(alert.textContent).toContain("Ask an admin");
        expect(screen.queryByText(/HttpError/)).toBeNull();
        expect(screen.queryByRole("link", { name: "Check the connection" })).toBeNull();
    });

    it("shows a load error with Try again, then recovers", async () => {
        mocks.list.mockResolvedValueOnce({ error: { detail: "boom" } });
        render(<BookingsPage />);

        const retry = await screen.findByRole("button", { name: "Try again" });
        expect(screen.getByRole("alert")).toBeTruthy();
        fireEvent.click(retry);
        expect(await screen.findByText("Mary Byrne")).toBeTruthy();
        expect(mocks.list).toHaveBeenCalledTimes(2);
    });

    it("handles a network failure while loading", async () => {
        mocks.list.mockRejectedValueOnce(new TypeError("Failed to fetch"));
        render(<BookingsPage />);
        expect(await screen.findByText("Couldn't load bookings. Please try again.")).toBeTruthy();
        expect(screen.queryByText(/Failed to fetch/)).toBeNull();
    });

    it("keeps the switch as it was when saving fails", async () => {
        mocks.update.mockResolvedValue({ error: { detail: "nope" } });
        render(<BookingsPage />);
        const toggle = await screen.findByRole("switch", { name: "Let the agent book" });

        fireEvent.click(toggle);

        await waitFor(() => expect(toast.error).toHaveBeenCalled());
        expect(toggle.getAttribute("aria-checked")).toBe("true");
        expect(screen.getByText("Agent books")).toBeTruthy();
        expect(toast.success).not.toHaveBeenCalled();
    });

    it("keeps the switch as it was when the network fails", async () => {
        mocks.update.mockRejectedValue(new TypeError("Failed to fetch"));
        render(<BookingsPage />);
        const toggle = await screen.findByRole("switch", { name: "Let the agent book" });
        fireEvent.click(toggle);
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Couldn't change the setting. Please try again."));
        expect(toggle.getAttribute("aria-checked")).toBe("true");
    });

    it("saves booking rules and shows the new summary", async () => {
        mocks.update.mockResolvedValue({ data: { rules: { max_bookings_at_once: 3 } } });
        render(<BookingsPage />);
        fireEvent.click(await screen.findByRole("button", { name: "Edit booking rules" }));
        fireEvent.change(screen.getByLabelText("Bookings at the same time"), { target: { value: "3" } });
        fireEvent.click(screen.getByRole("button", { name: "Save booking rules" }));

        await waitFor(() =>
            expect(mocks.update).toHaveBeenCalledWith({
                path: { connection_id: CAL },
                body: { rules: { max_bookings_at_once: 3 } },
            }),
        );
        expect(await screen.findByText(/3 bookings at the same time/)).toBeTruthy();
        expect(toast.success).toHaveBeenCalled();
    });

    it("tells the owner when booking rules could not be saved", async () => {
        mocks.update.mockResolvedValue({ error: { detail: "bad rules" } });
        render(<BookingsPage />);
        fireEvent.click(await screen.findByRole("button", { name: "Edit booking rules" }));
        fireEvent.change(screen.getByLabelText("Bookings at the same time"), { target: { value: "3" } });
        fireEvent.click(screen.getByRole("button", { name: "Save booking rules" }));

        await waitFor(() => expect(toast.error).toHaveBeenCalled());
        expect(screen.getByText(/^One booking at a time ·/)).toBeTruthy();
        expect(toast.success).not.toHaveBeenCalled();
    });

    it("hides the rules editor and switches from people who can't manage bookings", async () => {
        mocks.can.mockImplementation((...perms: string[]) => perms.every((p) => p === "calls:read"));
        render(<BookingsPage />);
        await screen.findByText("Mary Byrne");
        expect(screen.queryByRole("button", { name: "Edit booking rules" })).toBeNull();
        expect(screen.queryByRole("switch", { name: "Let the agent cancel or move bookings" })).toBeNull();
        expect(screen.getByText(/^One booking at a time ·/)).toBeTruthy();
    });

    it("shows an empty range in plain words and marks the chosen range", async () => {
        mocks.list.mockResolvedValue({ data: listing({ bookings: [] }) });
        render(<BookingsPage />);
        expect(await screen.findByText("No bookings yet in this range.")).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: "Last 7 days" }));
        expect(await screen.findByText("No bookings in the last 7 days.")).toBeTruthy();
        expect(screen.getByRole("button", { name: "Last 7 days" }).getAttribute("aria-pressed")).toBe("true");
    });
});
