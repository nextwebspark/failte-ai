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
});
