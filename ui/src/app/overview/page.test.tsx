import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DashboardSummaryResponse, FollowUpListResponse } from "@/client/types.gen";

import OverviewPage from "./page";

const mocks = vi.hoisted(() => ({
    perms: [] as string[],
    summary: vi.fn(),
    followUps: vi.fn(),
}));

vi.mock("@/client/sdk.gen", () => ({
    getDashboardSummaryApiV1DashboardSummaryGet: mocks.summary,
    listFollowUpsApiV1FollowUpsGet: mocks.followUps,
    countFollowUpsApiV1FollowUpsCountGet: vi.fn(async () => ({ data: { open: 0 } })),
}));
vi.mock("@/context/OrgConfigContext", () => ({
    useOrgConfig: () => ({ can: (...required: string[]) => required.every((p) => mocks.perms.includes(p)) }),
}));
vi.mock("@/lib/auth", () => ({
    useAuth: () => ({ user: { displayName: "Mary Byrne" }, provider: "stack" }),
}));

function summary(overrides: Partial<DashboardSummaryResponse> = {}): DashboardSummaryResponse {
    const hours = Array(24).fill(0);
    hours[12] = 3;
    hours[13] = 1;
    return {
        range: "today",
        timezone: "Europe/Dublin",
        workflow_id: null,
        start: "2026-11-05T00:00:00Z",
        end: "2026-11-05T13:41:00Z",
        tiles: {
            calls: 4,
            handled: 2,
            handled_percent: 50,
            passed_to_team: 1,
            transfer_picked_up: 0,
            transfer_not_answered: 1,
            hung_up_silent: 1,
            callbacks_requested: 0,
            in_progress: 0,
            average_call_seconds: 95,
        },
        previous_calls: 2,
        calls_change: null,
        calls_by_hour: hours,
        recent_calls: [
            {
                run_id: 501,
                workflow_id: 14,
                created_at: "2026-11-05T13:20:00Z",
                caller_number: "+353871234567",
                caller_name: "Declan Murphy",
                result: "booking_made",
                duration_seconds: 101,
                has_recording: true,
            },
        ],
        agent_status: {
            answering: true,
            reason: null,
            phone_numbers: ["+35315550142"],
            last_call_at: "2026-11-05T13:20:00Z",
        },
        credit: null,
        agents: [{ id: 14, name: "Bia Bistro bookings", active: true }],
        ...overrides,
    };
}

const NO_FOLLOW_UPS: FollowUpListResponse = {
    status: "open",
    items: [],
    kind_counts: { callback: 0, transfer_not_answered: 0, repeat_caller: 0 },
    open_count: 0,
    done_count: 0,
    week: { raised: 0, sorted: 0, median_wait_minutes: null },
};

describe("Home", () => {
    beforeEach(() => {
        mocks.perms = ["agents:read", "calls:read", "reports:read"];
        mocks.summary.mockReset();
        mocks.followUps.mockReset();
        mocks.summary.mockResolvedValue({ data: summary() });
        mocks.followUps.mockResolvedValue({ data: NO_FOLLOW_UPS });
    });

    it("greets the person as the page's one heading", async () => {
        render(<OverviewPage />);
        await screen.findByText("Handled by your agent", undefined, { timeout: 8000 });
        const headings = screen.getAllByRole("heading", { level: 1 });
        expect(headings).toHaveLength(1);
        expect(headings[0].textContent).toMatch(/^Good (morning|afternoon|evening), Mary$/);
    });

    it("shows the four tiles from the API's counts", async () => {
        render(<OverviewPage />);
        expect(await screen.findByText("Handled by your agent")).toBeTruthy();
        expect(screen.getByText("Passed to your team")).toBeTruthy();
        expect(screen.getByText("Hung up without speaking")).toBeTruthy();
        expect(screen.getByText("50%")).toBeTruthy();
        expect(screen.getAllByText("1 not answered").length).toBeGreaterThan(0);
        expect(screen.getAllByText(/Answering calls/).length).toBeGreaterThan(0);
    });

    it("asks the API again for 7 days", async () => {
        render(<OverviewPage />);
        await screen.findByText("Handled by your agent");
        fireEvent.click(screen.getByRole("button", { name: "7 days" }));
        await waitFor(() =>
            expect(mocks.summary).toHaveBeenLastCalledWith({ query: { range: "7d", workflow_id: null } }),
        );
    });

    it("links recent calls to the call and the quick links to the agent", async () => {
        render(<OverviewPage />);
        await screen.findByText("Recent calls");
        const listen = screen.getAllByRole("link", { name: /listen to the call from declan murphy/i });
        expect(listen[0].getAttribute("href")).toBe("/workflow/14/run/501?from=%2Foverview");
        const quick = within(screen.getByRole("navigation", { name: "Quick links" }));
        expect(quick.getByRole("link", { name: /opening hours/i }).getAttribute("href")).toBe("/workflow/14/facts");
        expect(quick.getByRole("link", { name: /try your agent/i }).getAttribute("href")).toBe(
            "/workflow/14/home?onboarding=web_call",
        );
        expect(screen.getByText("All caught up")).toBeTruthy();
    });

    it("warns when the agent isn't answering, with the fix the member may use", async () => {
        mocks.perms = [...mocks.perms, "billing:read"];
        mocks.summary.mockResolvedValue({
            data: summary({
                agent_status: { answering: false, reason: "no_credit", phone_numbers: ["+35315550142"], last_call_at: null },
            }),
        });
        render(<OverviewPage />);
        const alert = await screen.findByRole("alert");
        expect(alert.textContent).toMatch(/isn't answering/);
        expect(within(alert).getByRole("link", { name: "Top up credit" }).getAttribute("href")).toBe("/billing");
    });

    it("gives a brand-new business a checklist and a first call to make", async () => {
        mocks.summary.mockResolvedValue({
            data: summary({
                tiles: { ...summary().tiles, calls: 0, handled: 0, handled_percent: null },
                recent_calls: [],
                agent_status: { answering: true, reason: null, phone_numbers: ["+35315550142"], last_call_at: null },
            }),
        });
        render(<OverviewPage />);
        expect(await screen.findByText("Ring your number now")).toBeTruthy();
        expect(screen.getByText("Take your first call")).toBeTruthy();
        expect(screen.queryByText("Handled by your agent")).toBeNull();
    });

    it("offers to try again when the numbers can't load", async () => {
        mocks.summary.mockResolvedValueOnce({ error: { detail: "boom" } });
        render(<OverviewPage />);
        expect(await screen.findByText("We couldn't load your calls")).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: /try again/i }));
        expect(await screen.findByText("Handled by your agent")).toBeTruthy();
    });
});
