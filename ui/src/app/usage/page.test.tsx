import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import UsagePage from "./page";

const mocks = vi.hoisted(() => ({
    history: vi.fn(),
    push: vi.fn(),
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

vi.mock("@/client/sdk.gen", () => ({
    getUsageHistoryApiV1OrganizationsUsageRunsGet: mocks.history,
    getDailyUsageBreakdownApiV1OrganizationsUsageDailyBreakdownGet: vi.fn(async () => ({ data: null })),
    getPreferencesApiV1OrganizationsPreferencesGet: vi.fn(async () => ({ data: { timezone: "UTC" } })),
    getWorkflowsSummaryApiV1WorkflowSummaryGet: vi.fn(async () => ({ data: [] })),
    downloadUsageRunsReportApiV1OrganizationsUsageRunsReportGet: vi.fn(),
    savePreferencesApiV1OrganizationsPreferencesPut: vi.fn(),
}));
vi.mock("next/navigation", () => ({
    useRouter: () => ({ push: mocks.push, replace: vi.fn() }),
    useSearchParams: () => new URLSearchParams(mocks.query),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => mocks.auth }));
vi.mock("@/context/UserConfigContext", () => ({ useUserConfig: () => mocks.userConfig }));
vi.mock("@/context/AppConfigContext", () => ({ useAppConfig: () => ({ config: null }) }));
vi.mock("@/hooks/useDispositionCodes", () => ({ useDispositionCodes: () => ({ codes: [] }) }));
vi.mock("@/hooks/useFeatureFlags", () => ({ useFeatureEnabled: () => false }));
vi.mock("@/components/filters/FilterBuilder", () => ({ FilterBuilder: () => null }));
vi.mock("@/components/DailyUsageTable", () => ({ DailyUsageTable: () => null }));
vi.mock("@/components/privacy/CallerDataRequestDialog", () => ({ CallerDataRequestDialog: () => null }));
vi.mock("@/components/CallTypeCell", () => ({ CallTypeCell: () => <span>Phone</span> }));
vi.mock("react-timezone-select", () => ({ default: () => null }));
vi.mock("posthog-js", () => ({ default: { capture: vi.fn() } }));
vi.mock("@/lib/files", () => ({ downloadFile: vi.fn(), getSignedUrl: vi.fn(async () => null) }));

const RUNS = {
    runs: [
        {
            id: 501,
            workflow_id: 4,
            workflow_name: "Front desk",
            call_type: "inbound",
            caller_number: "+353871234567",
            created_at: "2026-11-01T10:00:00Z",
            call_duration_seconds: 65,
            recording_url: "rec/501.wav",
            transcript_url: null,
        },
    ],
    total_count: 1,
    page: 1,
    limit: 50,
    total_pages: 1,
    total_dograh_tokens: 0,
    total_duration_seconds: 65,
};

describe("UsagePage call list", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.query = "";
        mocks.history.mockResolvedValue({ data: RUNS });
    });

    it("opens a call through a real link that keeps the list to come back to", async () => {
        mocks.query = "page=2";
        render(<UsagePage />);
        const link = await screen.findByRole("link", { name: "Open call #501" });
        const href = link.getAttribute("href") ?? "";
        expect(href.startsWith("/workflow/4/run/501")).toBe(true);
        expect(decodeURIComponent(href)).toContain("/usage?page=2");
        expect(mocks.push).not.toHaveBeenCalled();
    });

    it("has no click handler on the row and no control inside the link", async () => {
        render(<UsagePage />);
        const link = await screen.findByRole("link", { name: "Open call #501" });
        expect(link.querySelector("a, button")).toBeNull();
        const row = link.closest("tr") as HTMLElement;
        expect(row.getAttribute("role")).toBeNull();
        expect(row.getAttribute("tabindex")).toBeNull();
    });

    it("keeps the recording button separate and named", async () => {
        render(<UsagePage />);
        await screen.findByRole("link", { name: "Open call #501" });
        const play = screen.getByRole("button", { name: "Play recording or read transcript for call #501" });
        expect(play.closest("a")).toBeNull();
    });

    it("sorts by duration from a keyboard-reachable button", async () => {
        render(<UsagePage />);
        await screen.findByRole("link", { name: "Open call #501" });
        const sort = screen.getByRole("button", { name: /Duration/ });
        expect(sort.tagName).toBe("BUTTON");
        fireEvent.click(sort);
        await waitFor(() => expect(mocks.push).toHaveBeenCalled());
        expect(mocks.push.mock.calls[0][0]).toContain("sort_by=duration");
    });
});
