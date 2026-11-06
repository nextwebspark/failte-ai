import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkflowRunResponseSchema } from "@/client/types.gen";

import { WorkflowRunsTable, type WorkflowRunsTableProps } from "./WorkflowRunsTable";

vi.mock("posthog-js", () => ({ default: { capture: vi.fn() } }));
vi.mock("@/lib/files", () => ({ downloadFile: vi.fn(), getSignedUrl: vi.fn(async () => null) }));
vi.mock("@/hooks/useOrganizationTimezone", () => ({ useOrganizationTimezone: () => "UTC" }));
vi.mock("@/components/CallTypeCell", () => ({ CallTypeCell: () => <span>Phone</span> }));
vi.mock("@/components/filters/FilterBuilder", () => ({ FilterBuilder: () => null }));

function run(id: number, overrides: Partial<WorkflowRunResponseSchema> = {}): WorkflowRunResponseSchema {
    return {
        id,
        workflow_id: 7,
        name: `Run ${id}`,
        mode: "twilio",
        is_completed: true,
        created_at: "2026-11-01T10:00:00Z",
        recording_url: null,
        transcript_url: null,
        cost_info: { call_duration_seconds: 42 },
        ...overrides,
    } as WorkflowRunResponseSchema;
}

function props(overrides: Partial<WorkflowRunsTableProps> = {}): WorkflowRunsTableProps {
    return {
        runs: [run(11), run(12, { workflow_id: 9, recording_url: "rec/12.wav" })],
        loading: false,
        error: null,
        currentPage: 1,
        totalPages: 1,
        totalCount: 2,
        onPageChange: vi.fn(),
        availableAttributes: [],
        activeFilters: [],
        onFiltersChange: vi.fn(),
        onApplyFilters: vi.fn(),
        onClearFilters: vi.fn(),
        isExecutingFilters: false,
        workflowId: 7,
        showFilters: false,
        ...overrides,
    };
}

describe("WorkflowRunsTable", () => {
    beforeEach(() => vi.clearAllMocks());

    it("makes each call a real link to the call, using the call's own agent", () => {
        render(<WorkflowRunsTable {...props()} />);
        expect(screen.getByRole("link", { name: "Open call #11" }).getAttribute("href")).toBe("/workflow/7/run/11");
        expect(screen.getByRole("link", { name: "Open call #12" }).getAttribute("href")).toBe("/workflow/9/run/12");
    });

    it("carries the list's URL so the call screen can go back to it", () => {
        render(<WorkflowRunsTable {...props({ returnTo: "/usage?page=2" })} />);
        const href = screen.getByRole("link", { name: "Open call #11" }).getAttribute("href") ?? "";
        expect(href.startsWith("/workflow/7/run/11?")).toBe(true);
        expect(decodeURIComponent(href)).toContain("/usage?page=2");
    });

    it("rows are not fake buttons: no click handler or role on the row, one link per row", () => {
        render(<WorkflowRunsTable {...props()} />);
        const row = screen.getByRole("link", { name: "Open call #11" }).closest("tr") as HTMLElement;
        expect(row.getAttribute("role")).toBeNull();
        expect(row.getAttribute("tabindex")).toBeNull();
        // The open link and the new-tab link; nothing interactive nested inside another.
        const links = within(row).getAllByRole("link");
        for (const link of links) {
            expect(link.querySelector("a, button")).toBeNull();
        }
    });

    it("opens a call in a new tab with a real link, not window.open", () => {
        const open = vi.spyOn(window, "open").mockImplementation(() => null);
        render(<WorkflowRunsTable {...props()} />);
        const newTab = screen.getByRole("link", { name: "Open call #11 in a new tab" });
        expect(newTab.getAttribute("href")).toBe("/workflow/7/run/11");
        expect(newTab.getAttribute("target")).toBe("_blank");
        expect(newTab.getAttribute("rel")).toContain("noopener");
        fireEvent.click(newTab);
        expect(open).not.toHaveBeenCalled();
        open.mockRestore();
    });

    it("names the recording button, and shows it only when there is one", () => {
        render(<WorkflowRunsTable {...props()} />);
        expect(screen.getByRole("button", { name: "Play recording or read transcript for call #12" })).toBeTruthy();
        expect(screen.queryByRole("button", { name: /call #11$/ })).toBeNull();
    });

    it("sorts by duration from a real button", () => {
        const onSort = vi.fn();
        render(<WorkflowRunsTable {...props({ onSort, sortBy: "duration", sortOrder: "asc" })} />);
        const sort = screen.getByRole("button", { name: /Duration/ });
        fireEvent.click(sort);
        expect(onSort).toHaveBeenCalledWith("duration");
        expect(sort.closest("th")?.getAttribute("aria-sort")).toBe("ascending");
    });

    it("names the reload button", () => {
        const onReload = vi.fn();
        render(<WorkflowRunsTable {...props({ onReload })} />);
        fireEvent.click(screen.getByRole("button", { name: "Reload calls" }));
        expect(onReload).toHaveBeenCalled();
    });

    it("shows the empty message", () => {
        render(<WorkflowRunsTable {...props({ runs: [], emptyMessage: "No calls yet" })} />);
        expect(screen.getByText("No calls yet")).toBeTruthy();
        expect(screen.queryByRole("link")).toBeNull();
    });

    it("shows an error as an alert", () => {
        render(<WorkflowRunsTable {...props({ error: "Couldn't load calls" })} />);
        expect(screen.getByRole("alert").textContent).toBe("Couldn't load calls");
    });

    it("pages forward and back, and disables the ends", () => {
        const onPageChange = vi.fn();
        render(<WorkflowRunsTable {...props({ totalPages: 3, currentPage: 1, onPageChange })} />);
        expect(screen.getByRole("button", { name: "Previous" }).hasAttribute("disabled")).toBe(true);
        fireEvent.click(screen.getByRole("button", { name: "Next" }));
        expect(onPageChange).toHaveBeenCalledWith(2);
    });
});
