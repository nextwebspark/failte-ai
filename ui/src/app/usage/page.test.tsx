import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import UsagePage from "./page";

const mocks = vi.hoisted(() => ({
    history: vi.fn(),
    run: vi.fn(),
    // Stable, as the real hook keeps it in state: a new array each render loops the filter sync.
    noCodes: [] as string[],
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    query: "",
    auth: { isAuthenticated: true, loading: false, user: { id: "u1" }, getAccessToken: async () => "t" },
    userConfig: {
        organizationPricing: null,
        can: () => true,
        userConfig: null,
    },
}));

vi.stubGlobal(
    "ResizeObserver",
    class {
        observe() {}
        unobserve() {}
        disconnect() {}
    },
);

// Answers "(min-width: Npx)" from window.innerWidth, as a browser would.
vi.stubGlobal("matchMedia", (query: string) => ({
    matches: window.innerWidth >= Number(/min-width:\s*(\d+)px/.exec(query)?.[1] ?? Infinity),
    media: query,
    addEventListener() {},
    removeEventListener() {},
}));

vi.mock("@/client/sdk.gen", () => ({
    getUsageHistoryApiV1OrganizationsUsageRunsGet: mocks.history,
    getWorkflowRunApiV1WorkflowWorkflowIdRunsRunIdGet: mocks.run,
    getDailyUsageBreakdownApiV1OrganizationsUsageDailyBreakdownGet: vi.fn(async () => ({ data: null })),
    getPreferencesApiV1OrganizationsPreferencesGet: vi.fn(async () => ({ data: { timezone: "UTC" } })),
    getWorkflowsSummaryApiV1WorkflowSummaryGet: vi.fn(async () => ({ data: [] })),
    downloadUsageRunsReportApiV1OrganizationsUsageRunsReportGet: vi.fn(),
    listRecordingSharesApiV1CallsRunIdRecordingSharesGet: vi.fn(async () => ({ data: { shares: [] } })),
    createRecordingShareApiV1CallsRunIdRecordingSharesPost: vi.fn(),
    revokeRecordingShareApiV1CallsRunIdRecordingSharesShareIdDelete: vi.fn(),
    savePreferencesApiV1OrganizationsPreferencesPut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
    useRouter: () => ({ push: mocks.push, replace: mocks.replace, back: mocks.back }),
    useSearchParams: () => new URLSearchParams(mocks.query),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => mocks.auth }));
vi.mock("@/context/UserConfigContext", () => ({ useUserConfig: () => mocks.userConfig }));
vi.mock("@/context/OrgConfigContext", () => ({ useOrgConfig: () => ({ orgContext: { organization_name: "Trattoria Bella" } }) }));
vi.mock("@/hooks/useDispositionCodes", () => ({ useDispositionCodes: () => ({ codes: mocks.noCodes }) }));
vi.mock("@/hooks/useFeatureFlags", () => ({ useFeatureEnabled: () => false }));
vi.mock("@/components/filters/FilterBuilder", () => ({ FilterBuilder: () => null }));
vi.mock("@/components/DailyUsageTable", () => ({ DailyUsageTable: () => null }));
vi.mock("@/components/privacy/CallerDataRequestDialog", () => ({ CallerDataRequestDialog: () => <button type="button">Caller data request</button> }));
vi.mock("react-timezone-select", () => ({ default: () => null }));
vi.mock("posthog-js", () => ({ default: { capture: vi.fn() } }));
vi.mock("@/lib/files", () => ({ downloadFile: vi.fn(), getSignedUrl: vi.fn(async () => "https://files.example/rec.wav") }));

const RUN = {
    id: 501,
    workflow_id: 4,
    workflow_name: "Front desk",
    name: "WR-501",
    mode: "twilio",
    call_type: "inbound",
    caller_number: "+353871234567",
    called_number: "+35315550142",
    created_at: "2026-11-01T10:00:00Z",
    call_duration_seconds: 65,
    dograh_token_usage: 0,
    recording_url: "recordings/501.wav",
    transcript_url: null,
    disposition: "callback_requested",
    gathered_context: {
        mapped_call_disposition: "callback_requested",
        extracted_variables: { caller_name: "Sinéad O'Brien", call_reason: "Wants to change Saturday to 7 people" },
    },
};

// The total is the API's count, larger than the page: tab counts must show it.
const PAGE = {
    runs: [RUN],
    total_count: 37,
    page: 1,
    limit: 10,
    total_pages: 4,
    total_dograh_tokens: 0,
    total_duration_seconds: 65,
};

const EMPTY = { ...PAGE, runs: [], total_count: 0, total_pages: 0 };

function requests() {
    return mocks.history.mock.calls.map(([options]) => options.query as Record<string, string | number>);
}

describe("Calls list", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        window.localStorage.clear();
        mocks.query = "";
        window.innerWidth = 1200;
        mocks.history.mockResolvedValue({ data: PAGE });
        mocks.run.mockResolvedValue({
            data: {
                is_completed: true,
                recording_url: "recordings/501.wav",
                transcript_url: null,
                gathered_context: RUN.gathered_context,
                logs: {
                    realtime_feedback_events: [
                        { type: "rtf-bot-text", payload: { text: "Hi, thanks for calling." }, timestamp: "2026-11-01T10:00:01Z", turn: 1 },
                        { type: "rtf-user-transcription", payload: { text: "Can I change my booking?", final: true }, timestamp: "2026-11-01T10:00:05Z", turn: 1 },
                    ],
                },
            },
        });
    });

    it("has one main title and a download that is always there", async () => {
        mocks.history.mockResolvedValue({ data: EMPTY });
        render(<UsagePage />);
        expect(screen.getByRole("heading", { level: 1, name: "Calls" })).toBeTruthy();
        expect(await screen.findByText("No calls yet")).toBeTruthy();
        expect((screen.getByRole("button", { name: "Download list" }) as HTMLButtonElement).disabled).toBe(false);
    });

    it("asks for the last 7 days by default, ten to a page", async () => {
        render(<UsagePage />);
        await screen.findByText("Sinéad O'Brien");
        const [list] = requests();
        expect(list.limit).toBe(10);
        expect(list.start_date).toBeTruthy();
        expect(list.filters).toBeUndefined();
        expect(screen.getByRole("button", { name: /Last 7 days/ })).toBeTruthy();
    });

    it("counts each tab with the API's totals, not the page length", async () => {
        render(<UsagePage />);
        await screen.findByText("Sinéad O'Brien");
        await waitFor(() => expect(requests()).toHaveLength(4));
        const tabFilters = requests().slice(1).map(query => JSON.parse(String(query.filters))[0].attribute);
        expect(tabFilters.sort()).toEqual(["bookingOutcome", "handledBy", "needsFollowUp"]);
        expect(await screen.findByRole("button", { name: "Needs follow-up, 37 calls" })).toBeTruthy();
        // Needs follow-up keeps Follow-ups' own 30 days, so it sends no dates.
        const followUp = requests().find(query => String(query.filters).includes("needsFollowUp"))!;
        expect(followUp.start_date).toBeUndefined();
        expect(JSON.parse(String(followUp.filters))[0]).toEqual({ attribute: "needsFollowUp", type: "runIds", value: {} });
        const order = screen.getAllByRole("button", { pressed: false }).concat(screen.getAllByRole("button", { pressed: true }))
            .map(button => button.getAttribute("aria-label") ?? "")
            .filter(label => /calls$/.test(label));
        expect(order.length).toBe(4);
        expect(await screen.findByRole("button", { name: "All, 37 calls" })).toBeTruthy();
        expect(screen.getByRole("button", { name: "Passed to team, 37 calls" })).toBeTruthy();
        const pager = screen.getByRole("navigation", { name: "Pages of calls" });
        expect(pager.textContent).toContain("Showing 1–10 of 37 calls");
    });

    it("opens a call from a real link over the whole row, with the play button apart", async () => {
        mocks.query = "page=2";
        render(<UsagePage />);
        const link = await screen.findByRole("link", { name: /Sinéad O'Brien/ });
        expect(link.getAttribute("href")).toBe("/usage?page=2&call=501");
        expect(link.querySelector("a, button")).toBeNull();
        const row = link.closest("tr") as HTMLElement;
        expect(row.className).toContain("relative");
        const play = screen.getByRole("button", { name: /Play the recording: Sinéad O'Brien/ });
        expect(play.closest("a")).toBeNull();
        fireEvent.click(play);
        expect(mocks.push.mock.calls[0][0]).toBe("/usage?page=2&call=501&play=1");
    });

    it("shows what the agent took down, in plain words", async () => {
        render(<UsagePage />);
        expect(await screen.findByText("Wants to change Saturday to 7 people")).toBeTruthy();
        expect(screen.getByText("Callback requested")).toBeTruthy();
        expect(screen.getByText("1:05")).toBeTruthy();
        expect(screen.getByText("+353 87 123 4567")).toBeTruthy();
    });

    it("searches names and numbers through the API", async () => {
        render(<UsagePage />);
        await screen.findByText("Sinéad O'Brien");
        const box = screen.getByRole("searchbox", { name: "Search names, numbers or what was said" });
        fireEvent.change(box, { target: { value: "murphy" } });
        fireEvent.submit(box.closest("form")!);
        expect(mocks.push.mock.calls.at(-1)![0]).toBe("/usage?q=murphy");
    });

    it("sends the search and chips from the URL as filters", async () => {
        mocks.query = "q=087%20123&who=team&outcome=XFER&when=all";
        render(<UsagePage />);
        await screen.findByText("Sinéad O'Brien");
        const [list] = requests();
        expect(list.start_date).toBeUndefined();
        expect(JSON.parse(String(list.filters))).toEqual([
            { attribute: "callerSearch", type: "text", value: { value: "087 123" } },
            { attribute: "dispositionCode", type: "multiSelect", value: { codes: ["XFER"] } },
            { attribute: "handledBy", type: "radio", value: { status: "team" } },
        ]);
    });

    it("says plainly when nothing matches and offers to clear the filters", async () => {
        mocks.history.mockImplementation(async ({ query }) => ({ data: query.filters ? EMPTY : { ...PAGE, total_count: 5 } }));
        mocks.query = "q=zzzz";
        render(<UsagePage />);
        expect(await screen.findByText("No calls match")).toBeTruthy();
        expect(screen.getByText("Nothing for “zzzz” in the last 7 days.")).toBeTruthy();
        fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
        expect(mocks.push.mock.calls.at(-1)![0]).toBe("/usage?when=all");
    });

    it("shows a friendly error with Try again, not the server's words", async () => {
        mocks.history.mockResolvedValueOnce({ error: { detail: "Internal Server Error" } });
        render(<UsagePage />);
        expect(await screen.findByText("We couldn't load your calls")).toBeTruthy();
        expect(screen.queryByText(/Internal Server Error/)).toBeNull();
        fireEvent.click(screen.getByRole("button", { name: "Try again" }));
        expect(await screen.findByText("Sinéad O'Brien")).toBeTruthy();
    });

    it("shows the stored summary as what happened, and a live call as in progress", async () => {
        const live = { ...RUN, id: 502, created_at: new Date().toISOString(), is_completed: false, disposition: null, gathered_context: {} };
        const summarised = { ...RUN, summary: "Wants Saturday changed from 6 to 7 people.", is_completed: true };
        mocks.history.mockResolvedValue({ data: { ...PAGE, runs: [summarised, live] } });
        render(<UsagePage />);
        expect(await screen.findByText("Wants Saturday changed from 6 to 7 people.")).toBeTruthy();
        expect(screen.queryByText("Wants to change Saturday to 7 people")).toBeNull();
        expect(screen.getByText("In progress")).toBeTruthy();
        expect(screen.queryByText("Not recorded")).toBeNull();
    });

    it("shows the tabs in the mock's order", async () => {
        render(<UsagePage />);
        await screen.findByText("Sinéad O'Brien");
        const group = screen.getByRole("group", { name: "Which calls" });
        const labels = Array.from(group.querySelectorAll("button")).map(button => button.textContent?.replace(/[\d,]+$/, "").trim());
        expect(labels).toEqual(["All", "Needs follow-up", "Bookings", "Passed to team"]);
    });

    it("on Needs follow-up, gives the date chip way to Follow-ups' 30 days", async () => {
        mocks.query = "tab=follow_up";
        render(<UsagePage />);
        await screen.findByText("Sinéad O'Brien");
        const [list] = requests();
        expect(list.start_date).toBeUndefined();
        expect(screen.getByText("Last 30 days, as on Follow-ups")).toBeTruthy();
        expect(screen.queryByRole("button", { name: /Last 7 days/ })).toBeNull();
    });

    it("shows calls as cards on a phone, each a real link", async () => {
        window.innerWidth = 390;
        render(<UsagePage />);
        const link = await screen.findByRole("link", { name: /Sinéad O'Brien/ });
        expect(link.closest("table")).toBeNull();
        expect(link.closest("li")).toBeTruthy();
    });
});

describe("On a wide screen", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        window.localStorage.clear();
        mocks.query = "";
        window.innerWidth = 1500;
        mocks.history.mockResolvedValue({ data: PAGE });
        mocks.run.mockResolvedValue({
            data: { is_completed: true, recording_url: null, transcript_url: null, gathered_context: {}, logs: {} },
        });
    });

    it("shows the first call beside the list without taking focus, and closes it", async () => {
        render(<UsagePage />);
        const panel = await screen.findByRole("complementary", { name: "Sinéad O'Brien" });
        expect(panel.getAttribute("aria-modal")).toBeNull();
        expect(panel.contains(document.activeElement)).toBe(false);
        fireEvent.click(screen.getByRole("button", { name: "Close this call" }));
        await waitFor(() => expect(screen.queryByRole("complementary", { name: "Sinéad O'Brien" })).toBeNull());
        expect(mocks.push).not.toHaveBeenCalled();
    });
});

describe("One call", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        window.localStorage.clear();
        window.innerWidth = 390;
        mocks.query = "call=501";
        mocks.history.mockResolvedValue({ data: PAGE });
    });

    it("opens full-screen on a phone with the transcript, details and Call back", async () => {
        mocks.run.mockResolvedValue({
            data: {
                is_completed: true,
                recording_url: "recordings/501.wav",
                transcript_url: null,
                gathered_context: RUN.gathered_context,
                logs: {
                    realtime_feedback_events: [
                        { type: "rtf-bot-text", payload: { text: "Hi, thanks for calling." }, timestamp: "2026-11-01T10:00:01Z", turn: 1 },
                        { type: "rtf-user-transcription", payload: { text: "Can I change my booking?", final: true }, timestamp: "2026-11-01T10:00:05Z", turn: 1 },
                    ],
                },
            },
        });
        render(<UsagePage />);
        const dialog = await screen.findByRole("dialog", { name: "Sinéad O'Brien" });
        expect(dialog).toBeTruthy();
        expect(await screen.findByText("Can I change my booking?")).toBeTruthy();
        expect(screen.getByText("Reason for calling")).toBeTruthy();
        expect(screen.getByRole("link", { name: "Call back" }).getAttribute("href")).toBe("tel:+353871234567");
        expect(screen.getByRole("link", { name: /Open full page/ }).getAttribute("href")).toContain("/workflow/4/run/501");
        fireEvent.click(screen.getByRole("button", { name: "Back to calls" }));
        expect(mocks.replace).toHaveBeenCalledWith("/usage", { scroll: false });
    });

    it("says when a call is still going on", async () => {
        const live = { ...RUN, created_at: new Date().toISOString(), disposition: null, gathered_context: {} };
        mocks.history.mockResolvedValue({ data: { ...PAGE, runs: [live] } });
        mocks.run.mockResolvedValue({
            data: { is_completed: false, recording_url: null, transcript_url: null, gathered_context: {}, logs: {} },
        });
        render(<UsagePage />);
        expect(await screen.findByText(/This call is still going on/)).toBeTruthy();
        expect(screen.getAllByText("Call in progress").length).toBeGreaterThan(0);
    });

    it("doesn't call an old unfinished call live", async () => {
        mocks.run.mockResolvedValue({
            data: { is_completed: false, recording_url: null, transcript_url: null, gathered_context: {}, logs: {} },
        });
        render(<UsagePage />);
        expect(await screen.findByText("No recording was kept for this call.")).toBeTruthy();
        expect(screen.queryByText(/still going on/)).toBeNull();
    });

    it("says when the recording isn't ready yet", async () => {
        const fresh = { ...RUN, recording_url: null, created_at: new Date().toISOString() };
        mocks.history.mockResolvedValue({ data: { ...PAGE, runs: [fresh] } });
        mocks.run.mockResolvedValue({
            data: { is_completed: true, recording_url: null, transcript_url: null, gathered_context: {}, logs: {} },
        });
        render(<UsagePage />);
        expect(await screen.findByText(/The recording isn't ready yet/)).toBeTruthy();
    });
});

describe("The call's summary, questions and search", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        window.localStorage.clear();
        window.innerWidth = 390;
        mocks.query = "call=501&q=parking";
        const reviewed = {
            ...RUN,
            summary: "Booked a table for 4 tonight. Asked about parking.",
            reason_label: "Reservations",
            unanswered_questions: ["Do you have gluten-free pasta?"],
        };
        mocks.history.mockResolvedValue({ data: { ...PAGE, runs: [reviewed] } });
        mocks.run.mockResolvedValue({
            data: {
                is_completed: true,
                recording_url: "recordings/501.wav",
                transcript_url: null,
                gathered_context: RUN.gathered_context,
                logs: {
                    realtime_feedback_events: [
                        { type: "rtf-bot-text", payload: { text: "Hi, thanks for calling." }, timestamp: "2026-11-01T10:00:01Z", turn: 1 },
                        { type: "rtf-user-transcription", payload: { text: "Is there Parking near you?", final: true }, timestamp: "2026-11-01T10:00:05Z", turn: 1 },
                    ],
                },
            },
        });
    });

    it("shows the summary, what they wanted, and what the agent couldn't answer", async () => {
        render(<UsagePage />);
        await screen.findByRole("dialog", { name: "Sinéad O'Brien" });
        expect(screen.getByRole("heading", { name: "Summary" })).toBeTruthy();
        expect(screen.getAllByText("Booked a table for 4 tonight. Asked about parking.").length).toBeGreaterThan(0);
        expect(screen.getByText("Reservations")).toBeTruthy();
        expect(screen.getByRole("heading", { name: "Your agent couldn't answer" })).toBeTruthy();
        expect(screen.getByText("Do you have gluten-free pasta?")).toBeTruthy();
        expect(screen.getByRole("link", { name: "Add the answer in What your agent knows" }).getAttribute("href")).toBe("/workflow/4/facts");
    });

    it("marks the searched words in what was said", async () => {
        render(<UsagePage />);
        await screen.findByText("Is there", { exact: false });
        const mark = document.querySelector("mark");
        expect(mark?.textContent).toBe("Parking");
        expect(screen.getByText(/is marked in 1 line/)).toBeTruthy();
    });

    it("offers Share recording when there is one", async () => {
        render(<UsagePage />);
        expect(await screen.findByRole("button", { name: "Share recording" }, { timeout: 4000 })).toBeTruthy();
    });
});

describe("A workspace with no calls", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        window.localStorage.clear();
        mocks.query = "";
        window.innerWidth = 1200;
        mocks.history.mockResolvedValue({ data: EMPTY });
    });

    it("says there are no calls yet and points to trying the agent, with no made-up calls", async () => {
        render(<UsagePage />);
        expect(await screen.findByText("No calls yet")).toBeTruthy();
        expect(screen.getByText(/link a phone number/)).toBeTruthy();
        expect(screen.getByRole("link", { name: "Try your agent" }).getAttribute("href")).toBe("/workflow");
        expect(screen.queryByText("Declan Murphy")).toBeNull();
        expect(screen.queryByText(/sample/i)).toBeNull();
        expect(mocks.run).not.toHaveBeenCalled();
    });

    it("says nothing matches when there are calls, just not these", async () => {
        mocks.history.mockImplementation(async ({ query }) => ({
            data: query.limit === 1 && !query.filters && !query.start_date ? { ...PAGE, total_count: 1 } : EMPTY,
        }));
        render(<UsagePage />);
        expect(await screen.findByText("No calls match")).toBeTruthy();
        expect(screen.queryByText("No calls yet")).toBeNull();
    });
});
