import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CallNotificationSettingsResponse } from "@/client/types.gen";

import NotificationsSettingsPage from "./page";

const mocks = vi.hoisted(() => ({
    get: vi.fn(),
    put: vi.fn(),
    can: vi.fn<(permission: string) => boolean>(() => true),
    role: "viewer" as string | null,
}));

vi.mock("@/client/sdk.gen", () => ({
    getNotificationSettingsApiV1OrganizationsNotificationsGet: mocks.get,
    updateNotificationSettingsApiV1OrganizationsNotificationsPut: mocks.put,
}));

vi.mock("@/context/OrgConfigContext", () => ({
    useOrgConfig: () => ({ can: mocks.can, role: mocks.role, loading: false }),
}));

vi.mock("@/lib/auth", () => ({
    useAuth: () => ({ user: { id: "1" }, loading: false }),
}));

vi.mock("sonner", () => ({
    toast: { success: vi.fn(), error: vi.fn() },
}));

function response(overrides: Partial<CallNotificationSettingsResponse> = {}): CallNotificationSettingsResponse {
    return {
        email_enabled: true,
        email_on_booking: true,
        email_on_message: true,
        email_on_missed_call: true,
        email_members: true,
        extra_recipients: [],
        text_caller_booking_confirmation: true,
        member_recipients: ["owner@example.com", "admin@example.com"],
        email_available: true,
        sms_available: false,
        ...overrides,
    };
}

describe("NotificationsSettingsPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.can.mockImplementation(() => true);
        mocks.role = "viewer";
        mocks.get.mockResolvedValue({ data: response() });
        mocks.put.mockImplementation(async ({ body }) => ({ data: response(body) }));
    });

    it("shows the toggles, who gets the emails, and that texting isn't set up", async () => {
        render(<NotificationsSettingsPage />);

        expect(await screen.findByRole("switch", { name: "When a call is missed" })).toBeTruthy();
        expect(screen.getByRole("switch", { name: "When a booking is made, moved or cancelled" }).getAttribute("aria-checked")).toBe("true");
        expect(screen.getByText("owner@example.com, admin@example.com")).toBeTruthy();
        expect(screen.getByRole("switch", { name: "Text callers a booking confirmation" })).toBeTruthy();
        expect(screen.getByText(/Texting isn't set up yet/)).toBeTruthy();
        expect(screen.queryByText(/Email isn't set up/)).toBeNull();
    });

    it("saves a toggle straight away", async () => {
        render(<NotificationsSettingsPage />);
        fireEvent.click(await screen.findByRole("switch", { name: "When a call is missed" }));

        await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
        expect(mocks.put.mock.calls[0][0].body).toMatchObject({
            email_on_missed_call: false,
            email_on_booking: true,
            text_caller_booking_confirmation: true,
        });
        await waitFor(() =>
            expect(
                screen.getByRole("switch", { name: "When a call is missed" }).getAttribute("aria-checked"),
            ).toBe("false"),
        );
    });

    it("turning email off greys out the email choices", async () => {
        mocks.get.mockResolvedValue({ data: response({ email_enabled: false }) });
        render(<NotificationsSettingsPage />);

        const booking = await screen.findByRole("switch", { name: "When a booking is made, moved or cancelled" });
        expect(booking.hasAttribute("disabled")).toBe(true);
        // Texts are separate from the business emails.
        expect(
            screen.getByRole("switch", { name: "Text callers a booking confirmation" }).hasAttribute("disabled"),
        ).toBe(false);
    });

    it("adds and removes an extra address", async () => {
        render(<NotificationsSettingsPage />);
        const input = await screen.findByRole("textbox", { name: "Email address to add" });

        fireEvent.change(input, { target: { value: "chef@example.com" } });
        fireEvent.click(screen.getByRole("button", { name: "Add" }));

        await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
        expect(mocks.put.mock.calls[0][0].body.extra_recipients).toEqual(["chef@example.com"]);
        expect(await screen.findByText("chef@example.com")).toBeTruthy();

        fireEvent.click(screen.getByRole("button", { name: "Remove chef@example.com" }));
        await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(2));
        expect(mocks.put.mock.calls[1][0].body.extra_recipients).toEqual([]);
    });

    it("refuses something that isn't an address without saving", async () => {
        render(<NotificationsSettingsPage />);
        const input = await screen.findByRole("textbox", { name: "Email address to add" });

        fireEvent.change(input, { target: { value: "chef" } });
        fireEvent.click(screen.getByRole("button", { name: "Add" }));

        expect(toast.error).toHaveBeenCalled();
        expect(mocks.put).not.toHaveBeenCalled();
    });

    it("puts a toggle back when saving fails", async () => {
        mocks.put.mockResolvedValue({ error: { detail: "Server unavailable" } });
        render(<NotificationsSettingsPage />);
        const toggle = await screen.findByRole("switch", { name: "When a message is taken" });

        fireEvent.click(toggle);

        await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Server unavailable"));
        expect(screen.getByRole("switch", { name: "When a message is taken" }).getAttribute("aria-checked")).toBe(
            "true",
        );
    });

    it("tells staff they don't have access and loads nothing", () => {
        mocks.can.mockImplementation(() => false);
        mocks.role = "staff";
        render(<NotificationsSettingsPage />);

        expect(screen.getByText("You don't have access to this page")).toBeTruthy();
        expect(mocks.get).not.toHaveBeenCalled();
    });
});
