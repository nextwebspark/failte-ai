import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CampaignsPage from "./page";

const mocks = vi.hoisted(() => ({
    list: vi.fn(),
    perms: [] as string[],
}));

vi.mock("@/client/sdk.gen", () => ({ getCampaignsApiV1CampaignGet: mocks.list }));
vi.mock("@/lib/auth", () => ({
    useAuth: () => ({
        user: { id: "u1" },
        loading: false,
        getAccessToken: async () => "token",
        redirectToLogin: vi.fn(),
    }),
}));
vi.mock("@/context/OrgConfigContext", () => ({
    useOrgConfig: () => ({ can: (...required: string[]) => required.every((p) => mocks.perms.includes(p)) }),
}));
vi.mock("@/hooks/useOrganizationTimezone", () => ({ useOrganizationTimezone: () => "UTC" }));
vi.mock("@/components/layout/PageActionsSlot", () => ({
    PageActions: ({ children }: { children: ReactNode }) => <div data-testid="page-actions">{children}</div>,
}));

const CAMPAIGNS = {
    campaigns: [
        {
            id: 3,
            name: "November reminders",
            workflow_name: "Front desk",
            state: "running",
            executed_count: 4,
            total_queued_count: 10,
            created_at: "2026-11-01T10:00:00Z",
        },
    ],
};

describe("CampaignsPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.perms = ["campaigns:read", "campaigns:write"];
        mocks.list.mockResolvedValue({ data: CAMPAIGNS });
    });

    it("lists campaigns with the name as a real link", async () => {
        render(<CampaignsPage />);
        const link = await screen.findByRole("link", { name: "November reminders" });
        expect(link.getAttribute("href")).toBe("/campaigns/3");
        const row = link.closest("tr") as HTMLElement;
        expect(row.getAttribute("role")).toBeNull();
        // The View cue is not a second control.
        expect(row.querySelectorAll("a, button")).toHaveLength(1);
    });

    it("offers New campaign as a link to people who can create campaigns", async () => {
        render(<CampaignsPage />);
        await screen.findByRole("link", { name: "November reminders" });
        expect(screen.getByRole("link", { name: "New campaign" }).getAttribute("href")).toBe("/campaigns/new");
    });

    it("hides New campaign without campaigns:write", async () => {
        mocks.perms = ["campaigns:read"];
        render(<CampaignsPage />);
        await screen.findByRole("link", { name: "November reminders" });
        expect(screen.queryByRole("link", { name: "New campaign" })).toBeNull();
    });

    it("shows an empty state, with the create link only for those who can", async () => {
        mocks.list.mockResolvedValue({ data: { campaigns: [] } });
        render(<CampaignsPage />);
        expect(await screen.findByText("No campaigns yet")).toBeTruthy();
        expect(screen.getByRole("link", { name: "Create your first campaign" }).getAttribute("href")).toBe("/campaigns/new");
    });

    it("hides the empty-state create link without campaigns:write", async () => {
        mocks.perms = ["campaigns:read"];
        mocks.list.mockResolvedValue({ data: { campaigns: [] } });
        render(<CampaignsPage />);
        expect(await screen.findByText("No campaigns yet")).toBeTruthy();
        expect(screen.queryByRole("link", { name: "Create your first campaign" })).toBeNull();
    });

    it("shows an API error with Try again, then recovers", async () => {
        mocks.list.mockResolvedValueOnce({ error: { detail: "boom" } });
        render(<CampaignsPage />);
        expect((await screen.findByRole("alert")).textContent).toContain("Couldn't load your campaigns");
        fireEvent.click(screen.getByRole("button", { name: "Try again" }));
        expect(await screen.findByRole("link", { name: "November reminders" })).toBeTruthy();
        expect(mocks.list).toHaveBeenCalledTimes(2);
    });

    it("handles a network failure while loading", async () => {
        vi.spyOn(console, "error").mockImplementation(() => {});
        mocks.list.mockRejectedValueOnce(new TypeError("Failed to fetch"));
        render(<CampaignsPage />);
        await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
        expect(screen.queryByText(/Failed to fetch/)).toBeNull();
    });
});
