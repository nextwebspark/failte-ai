import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FollowUpItem, FollowUpListResponse } from "@/client/types.gen";

import FollowUpsPage from "./page";

const mocks = vi.hoisted(() => ({
    perms: [] as string[],
    list: vi.fn(),
    done: vi.fn(),
    undo: vi.fn(),
    push: vi.fn(),
    replace: vi.fn(),
    query: "",
}));

vi.mock("@/client/sdk.gen", () => ({
    listFollowUpsApiV1FollowUpsGet: mocks.list,
    markFollowUpDoneApiV1FollowUpsRunIdDonePost: mocks.done,
    undoFollowUpDoneApiV1FollowUpsRunIdDoneDelete: mocks.undo,
}));
vi.mock("next/navigation", () => ({
    useRouter: () => ({ push: mocks.push, replace: mocks.replace }),
    useSearchParams: () => new URLSearchParams(mocks.query),
}));
vi.mock("@/context/OrgConfigContext", () => ({
    useOrgConfig: () => ({ can: (...required: string[]) => required.every((p) => mocks.perms.includes(p)) }),
}));
vi.mock("@/hooks/useOrganizationTimezone", () => ({ useOrganizationTimezone: () => "Europe/Dublin" }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { id: "4" }, loading: false }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function item(overrides: Partial<FollowUpItem>): FollowUpItem {
    return {
        run_id: 1,
        workflow_id: 14,
        workflow_name: "Bia Bistro bookings",
        kind: "callback",
        created_at: "2026-11-05T10:42:00Z",
        caller_number: "+353871111111",
        caller_name: null,
        callback_number: null,
        call_reason: null,
        duration_seconds: 60,
        has_recording: true,
        repeat_count: null,
        first_call_at: null,
        done_at: null,
        done_by: null,
        summary: null,
        questions: [],
        ...overrides,
    };
}

function response(items: FollowUpItem[], status: "open" | "done" | "all" = "open"): FollowUpListResponse {
    const counts = { callback: 0, transfer_not_answered: 0, repeat_caller: 0, unanswered_question: 0, time_was_full: 0, other_language: 0, emergency: 0 };
    for (const i of items) counts[i.kind] += 1;
    return {
        status,
        start: "2026-10-06T10:00:00Z",
        end: "2026-11-05T12:00:00Z",
        timezone: "Europe/Dublin",
        items,
        kind_counts: counts,
        open_count: status === "open" ? items.length : 0,
        done_count: status === "done" ? items.length : 1,
        open_total: 2,
        week: { raised: 5, sorted: 3, median_wait_minutes: 100 },
        has_calls: true,
    };
}

const OPEN = [
    item({ run_id: 1, caller_name: "Sinéad O'Brien", call_reason: "Change Saturday to 7 people" }),
    item({ run_id: 2, kind: "transfer_not_answered", caller_number: "+353872222222", has_recording: false }),
];

describe("Follow-ups", () => {
    beforeEach(() => {
        mocks.perms = ["calls:read", "followups:manage"];
        mocks.list.mockReset();
        mocks.done.mockReset();
        mocks.push.mockReset();
        mocks.replace.mockReset();
        mocks.query = "";
        mocks.list.mockImplementation(async ({ query }: { query: { status: string } }) => ({
            data:
                query.status === "done"
                    ? response([item({ run_id: 3, done_at: "2026-11-05T11:20:00Z", done_by: "Maria" })], "done")
                    : response(OPEN),
        }));
        mocks.done.mockResolvedValue({ data: { run_id: 1, done_at: "2026-11-05T12:00:00Z", done_by: "Maria" } });
    });

    it("lists what needs a person, with the week's real counts", async () => {
        render(<FollowUpsPage />);
        expect(await screen.findByText("Call back Sinéad O'Brien", undefined, { timeout: 8000 })).toBeTruthy();
        expect(screen.getByText("Change Saturday to 7 people")).toBeTruthy();
        expect(screen.getAllByText("Transfer not answered").length).toBeGreaterThan(0);
        expect(screen.getByRole("tab", { name: /To do/ }).textContent).toContain("2");
        const week = within(screen.getByRole("complementary"));
        expect(week.getByText("Follow-ups raised").nextSibling?.textContent).toBe("5");
        expect(week.getByText("1 h 40 min")).toBeTruthy();
        // No email or text alert switches: nothing sends them yet.
        expect(screen.queryByRole("switch")).toBeNull();
    });

    it("puts the kind picked in the URL, and asks the API for it", async () => {
        render(<FollowUpsPage />);
        await screen.findByText("Call back Sinéad O'Brien");
        fireEvent.click(screen.getByRole("button", { name: /^Call back\s*1$/ }));
        expect(mocks.push).toHaveBeenCalledWith("/follow-ups?kind=callback", { scroll: false });

        mocks.query = "kind=callback&when=7d&q=saturday";
        mocks.list.mockClear();
        render(<FollowUpsPage />);
        await waitFor(() =>
            expect(mocks.list).toHaveBeenCalledWith({
                query: { status: "open", workflow_id: null, range: "7d", kind: "callback", q: "saturday" },
            }),
        );
    });

    it("sends days picked by hand, and the Done tab, from the URL", async () => {
        mocks.query = "status=done&when=custom&start=2026-11-02&end=2026-11-04";
        render(<FollowUpsPage />);
        await waitFor(() =>
            expect(mocks.list).toHaveBeenCalledWith({
                query: { status: "done", workflow_id: null, start_date: "2026-11-02", end_date: "2026-11-04" },
            }),
        );
        expect(await screen.findByRole("tab", { name: /Done/, selected: true })).toBeTruthy();
    });

    it("says how many match, and how many are open in all, when filtered", async () => {
        mocks.query = "kind=callback";
        mocks.list.mockResolvedValue({ data: { ...response([OPEN[0]]), open_total: 4 } });
        render(<FollowUpsPage />);
        await screen.findByText("Call back Sinéad O'Brien");
        expect(screen.getByText(/1 open follow-up in the last 30 days · Call back/)).toBeTruthy();
        expect(screen.getByText(/4 open in all/)).toBeTruthy();
    });

    it("offers Clear filters when nothing matches", async () => {
        mocks.query = "q=nobody";
        mocks.list.mockResolvedValue({ data: response([]) });
        render(<FollowUpsPage />);
        expect(await screen.findByText("Nothing matches")).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
        expect(mocks.push).toHaveBeenCalledWith("/follow-ups", { scroll: false });
    });

    it("marks one done and refreshes the list", async () => {
        render(<FollowUpsPage />);
        await screen.findByText("Call back Sinéad O'Brien");
        fireEvent.click(screen.getAllByRole("button", { name: "Mark done" })[0]);
        await waitFor(() => expect(mocks.done).toHaveBeenCalledWith({ path: { run_id: 1 } }));
        await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
    });

    it("shows who sorted a done item, with Undo", async () => {
        render(<FollowUpsPage />);
        await screen.findByText("Call back Sinéad O'Brien");
        fireEvent.click(screen.getByRole("tab", { name: /Done/ }));
        expect(mocks.push).toHaveBeenCalledWith("/follow-ups?status=done", { scroll: false });
        mocks.query = "status=done";
        render(<FollowUpsPage />);
        expect(await screen.findByText(/Maria/)).toBeTruthy();
        expect(screen.getByRole("button", { name: /Undo/ })).toBeTruthy();
    });

    it("hides Mark done from members who can't", async () => {
        mocks.perms = ["calls:read"];
        render(<FollowUpsPage />);
        await screen.findByText("Call back Sinéad O'Brien");
        expect(screen.queryByRole("button", { name: "Mark done" })).toBeNull();
    });

    it("says all caught up when nothing is waiting", async () => {
        mocks.list.mockResolvedValue({ data: response([]) });
        render(<FollowUpsPage />);
        expect(await screen.findByText("All caught up")).toBeTruthy();
        expect(screen.getByRole("link", { name: "See all calls" }).getAttribute("href")).toBe("/usage");
    });

    it("says there are no calls yet, not all caught up, before the first call", async () => {
        mocks.list.mockResolvedValue({ data: { ...response([]), has_calls: false } });
        render(<FollowUpsPage />);
        expect(await screen.findByText("No calls yet")).toBeTruthy();
        expect(screen.queryByText("All caught up")).toBeNull();
        expect(screen.queryByText(/sample/i)).toBeNull();
        expect(screen.getByRole("link", { name: "Go to Home" }).getAttribute("href")).toBe("/overview");
    });
});
