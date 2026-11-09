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
            bookings_taken: 1,
        },
        previous_calls: 2,
        calls_change: null,
        calls_by_hour: hours,
        after_hours: { calls: 2, agents_without_hours: [] },
        turned_away_today: { calls: 0, forwarded: 0, voicemails: 0 },
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
                summary: "Booked a table for 4 tonight at 7:00 pm.",
                reason_label: "Reservations",
            },
        ],
        callers_wanted: [
            { key: "reservations", label: "Reservations", count: 3, percent: 75 },
            { key: "other", label: "Other", count: 1, percent: 25 },
        ],
        wording: { template: "restaurant", bookings_label: "bookings taken" },
        has_calls: true,
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
    start: "2026-10-06T10:00:00Z",
    end: "2026-11-05T12:00:00Z",
    timezone: "Europe/Dublin",
    items: [],
    kind_counts: { callback: 0, transfer_not_answered: 0, repeat_caller: 0 },
    open_count: 0,
    done_count: 0,
    open_total: 0,
    week: { raised: 0, sorted: 0, median_wait_minutes: null },
    has_calls: true,
};

describe("Home", () => {
    beforeEach(() => {
        mocks.perms = ["agents:read", "calls:read", "reports:read"];
        mocks.summary.mockReset();
        mocks.followUps.mockReset();
        mocks.summary.mockResolvedValue({ data: summary() });
        mocks.followUps.mockResolvedValue({ data: NO_FOLLOW_UPS });
        window.localStorage.clear();
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

    it("says how many calls came in outside opening hours, and who isn't counted", async () => {
        mocks.summary.mockResolvedValue({
            data: summary({ after_hours: { calls: 2, agents_without_hours: [{ id: 15, name: "Front desk" }] } }),
        });
        render(<OverviewPage />);
        expect(await screen.findByText("2 calls came in outside opening hours")).toBeTruthy();
        expect(screen.getByText(/Not counted: Front desk/)).toBeTruthy();
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

    const BRAND_NEW = () =>
        summary({
            tiles: { ...summary().tiles, calls: 0, handled: 0, handled_percent: null },
            recent_calls: [],
            callers_wanted: [],
            has_calls: false,
            agent_status: { answering: true, reason: null, phone_numbers: ["+35315550142"], last_call_at: null },
        });

    it("gives a brand-new business the checklist and its agent, with no made-up calls or empty charts", async () => {
        mocks.summary.mockResolvedValue({ data: BRAND_NEW() });
        render(<OverviewPage />);
        expect(await screen.findByText("Ring your number now")).toBeTruthy();
        expect(screen.getByText("Take your first call")).toBeTruthy();
        expect(screen.getByText("Your agent")).toBeTruthy();
        expect(screen.getByText("No calls yet")).toBeTruthy();
        // No tiles, charts or sample calls until a real call comes in.
        expect(screen.queryByText("Handled by your agent")).toBeNull();
        expect(screen.queryByText("When people called")).toBeNull();
        expect(screen.queryByText("Declan Murphy")).toBeNull();
        expect(screen.queryByText(/sample/i)).toBeNull();
    });

    it("shows what callers wanted, with counts and percents, and the bookings taken", async () => {
        render(<OverviewPage />);
        const card = within((await screen.findByText("What callers wanted")).closest("section") as HTMLElement);
        expect(card.getByLabelText("Reservations: 3 calls, 75%")).toBeTruthy();
        expect(card.getByLabelText("Other: 1 call, 25%")).toBeTruthy();
        expect(card.getByText("bookings taken")).toBeTruthy();
        expect(card.getByText("average call")).toBeTruthy();
        expect(screen.getAllByText("Booked a table for 4 tonight at 7:00 pm.").length).toBeGreaterThan(0);
    });

    it("lists a question the agent couldn't answer with Add answer", async () => {
        mocks.perms = [...mocks.perms, "followups:manage", "agents:facts"];
        mocks.followUps.mockResolvedValue({
            data: {
                ...NO_FOLLOW_UPS,
                items: [
                    {
                        run_id: 7,
                        workflow_id: 14,
                        workflow_name: "Bia Bistro bookings",
                        kind: "unanswered_question",
                        created_at: "2026-11-05T12:00:00Z",
                        caller_number: "+353871234567",
                        caller_name: null,
                        callback_number: null,
                        call_reason: null,
                        duration_seconds: 40,
                        has_recording: true,
                        repeat_count: null,
                        first_call_at: null,
                        done_at: null,
                        done_by: null,
                        summary: "Asked about gluten-free pasta.",
                        questions: ["Do you have gluten-free pasta?"],
                    },
                ],
                open_count: 1,
            },
        });
        render(<OverviewPage />);
        expect(await screen.findByText("Your agent couldn't answer")).toBeTruthy();
        expect(screen.getByText("Add an answer")).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: /add answer/i }));
        expect(await screen.findByRole("dialog")).toBeTruthy();
        expect(within(screen.getByRole("dialog")).getByText("Do you have gluten-free pasta?")).toBeTruthy();
    });

    it("offers to try again when the numbers can't load", async () => {
        mocks.summary.mockResolvedValueOnce({ error: { detail: "boom" } });
        render(<OverviewPage />);
        expect(await screen.findByText("We couldn't load your calls")).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: /try again/i }));
        expect(await screen.findByText("Handled by your agent")).toBeTruthy();
    });
});
