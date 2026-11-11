import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ToolsPage from "./page";

const mocks = vi.hoisted(() => ({
    list: vi.fn(),
    remove: vi.fn(),
    restore: vi.fn(),
    push: vi.fn(),
    // One object, so the page's callbacks stay stable between renders.
    auth: { user: { id: "u1" }, loading: false, getAccessToken: async () => "token", redirectToLogin: () => {} },
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
    listToolsApiV1ToolsGet: mocks.list,
    deleteToolApiV1ToolsToolUuidDelete: mocks.remove,
    unarchiveToolApiV1ToolsToolUuidUnarchivePost: mocks.restore,
    createToolApiV1ToolsPost: vi.fn(),
    getWorkflowsSummaryApiV1WorkflowSummaryGet: vi.fn(async () => ({ data: [] })),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/lib/auth", () => ({ useAuth: () => mocks.auth }));
vi.mock("@/components/http", () => ({ CredentialSelector: () => null }));
vi.mock("@/components/layout/PageActionsSlot", () => ({
    PageActions: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

const TOOLS = [
    { tool_uuid: "t-1", name: "Check opening hours", description: "Looks up hours", category: "http_api", status: "active" },
    { tool_uuid: "t-2", name: "Old webhook", description: null, category: "http_api", status: "archived" },
];

describe("ToolsPage", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.list.mockResolvedValue({ data: TOOLS });
        mocks.remove.mockResolvedValue({ data: {} });
        mocks.restore.mockResolvedValue({ data: {} });
    });

    it("makes each tool's name a real link, active and archived", async () => {
        render(<ToolsPage />);
        expect((await screen.findByRole("link", { name: "Check opening hours" })).getAttribute("href")).toBe("/tools/t-1");
        expect(screen.getByRole("link", { name: "Old webhook" }).getAttribute("href")).toBe("/tools/t-2");
        expect(mocks.push).not.toHaveBeenCalled();
    });

    it("keeps the archive button separate from the link and names it", async () => {
        render(<ToolsPage />);
        const link = await screen.findByRole("link", { name: "Check opening hours" });
        const archive = screen.getByRole("button", { name: "Archive Check opening hours" });
        expect(link.contains(archive)).toBe(false);
        expect(archive.closest("a")).toBeNull();
        expect(screen.getByRole("button", { name: "Restore Old webhook" })).toBeTruthy();
    });

    it("archives after confirming", async () => {
        vi.spyOn(window, "confirm").mockReturnValue(true);
        render(<ToolsPage />);
        fireEvent.click(await screen.findByRole("button", { name: "Archive Check opening hours" }));
        await waitFor(() => expect(mocks.remove).toHaveBeenCalledWith(expect.objectContaining({ path: { tool_uuid: "t-1" } })));
        await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
        expect(mocks.push).not.toHaveBeenCalled();
    });

    it("does nothing when archiving is cancelled", async () => {
        vi.spyOn(window, "confirm").mockReturnValue(false);
        render(<ToolsPage />);
        fireEvent.click(await screen.findByRole("button", { name: "Archive Check opening hours" }));
        expect(mocks.remove).not.toHaveBeenCalled();
    });

    it("shows an archive refusal from the API", async () => {
        vi.spyOn(window, "confirm").mockReturnValue(true);
        mocks.remove.mockResolvedValue({ error: { detail: "The tool is used by an agent." } });
        render(<ToolsPage />);
        fireEvent.click(await screen.findByRole("button", { name: "Archive Check opening hours" }));
        expect((await screen.findByRole("alert")).textContent).toContain("The tool is used by an agent.");
    });

    it("shows a restore failure", async () => {
        vi.spyOn(console, "error").mockImplementation(() => {});
        mocks.restore.mockRejectedValue(new TypeError("Failed to fetch"));
        render(<ToolsPage />);
        fireEvent.click(await screen.findByRole("button", { name: "Restore Old webhook" }));
        expect((await screen.findByRole("alert")).textContent).toContain("Couldn't restore the tool");
    });

    it("shows a load error with Try again, then recovers", async () => {
        mocks.list.mockResolvedValueOnce({ error: { detail: "boom" } });
        render(<ToolsPage />);
        expect((await screen.findByRole("alert")).textContent).toContain("Couldn't load your tools");
        fireEvent.click(screen.getByRole("button", { name: "Try again" }));
        expect(await screen.findByRole("link", { name: "Check opening hours" })).toBeTruthy();
        expect(screen.queryByRole("alert")).toBeNull();
    });

    it("handles a network failure while loading", async () => {
        vi.spyOn(console, "error").mockImplementation(() => {});
        mocks.list.mockRejectedValueOnce(new TypeError("Failed to fetch"));
        render(<ToolsPage />);
        expect((await screen.findByRole("alert")).textContent).toContain("Couldn't load your tools");
    });

    it("shows the empty state", async () => {
        mocks.list.mockResolvedValue({ data: [] });
        render(<ToolsPage />);
        expect(await screen.findByText("No tools yet")).toBeTruthy();
        expect(screen.queryAllByRole("link")).toHaveLength(0);
    });
});
