import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HomeLayoutResponse } from "@/client/types.gen";

import HomeLayoutSettingsPage from "./page";

const mocks = vi.hoisted(() => ({
    get: vi.fn(),
    put: vi.fn(),
    del: vi.fn(),
    can: vi.fn<(permission: string) => boolean>(() => true),
    role: "viewer" as string | null,
}));

vi.mock("@/client/sdk.gen", () => ({
    getHomeLayoutApiV1DashboardLayoutGet: mocks.get,
    saveWorkspaceHomeLayoutApiV1DashboardLayoutWorkspacePut: mocks.put,
    clearWorkspaceHomeLayoutApiV1DashboardLayoutWorkspaceDelete: mocks.del,
}));

vi.mock("@/context/OrgConfigContext", () => ({
    useOrgConfig: () => ({ can: mocks.can, role: mocks.role, loading: false }),
}));

vi.mock("@/lib/auth", () => ({
    useAuth: () => ({ user: { id: "1" }, loading: false }),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function response(workspace: HomeLayoutResponse["workspace_default"] = null): HomeLayoutResponse {
    return {
        layout: workspace ?? { hidden: [], pinned: [] },
        source: workspace ? "workspace" : "default",
        workspace_default: workspace,
        can_set_workspace_default: true,
        cards: [
            { id: "tiles", label: "Call numbers" },
            { id: "attention", label: "Needs your attention" },
            { id: "recent-calls", label: "Recent calls" },
        ],
    };
}

describe("Settings > Home layout", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.can.mockImplementation(() => true);
        mocks.get.mockResolvedValue({ data: response() });
        mocks.put.mockImplementation(async ({ body }) => ({ data: response(body) }));
        mocks.del.mockResolvedValue({ data: response() });
    });

    it("lets the owner choose the cards everyone starts with", async () => {
        render(<HomeLayoutSettingsPage />);
        expect(await screen.findByText(/No workspace layout yet/)).toBeTruthy();
        const tiles = screen.getByRole("switch", { name: "Call numbers" });
        expect(tiles.getAttribute("aria-checked")).toBe("true");
        expect(screen.getByRole("button", { name: "Save for everyone" }).hasAttribute("disabled")).toBe(true);

        fireEvent.click(tiles);
        fireEvent.click(screen.getByRole("button", { name: "Save for everyone" }));
        await waitFor(() => expect(mocks.put).toHaveBeenCalledWith({ body: { hidden: ["tiles"], pinned: [] } }));
        expect(await screen.findByText("Your workspace has its own Home layout.")).toBeTruthy();
    });

    it("goes back to the standard layout", async () => {
        mocks.get.mockResolvedValue({ data: response({ hidden: ["tiles"], pinned: ["attention"] }) });
        render(<HomeLayoutSettingsPage />);
        fireEvent.click(await screen.findByRole("button", { name: "Use the standard layout" }));
        await waitFor(() => expect(mocks.del).toHaveBeenCalledTimes(1));
        expect(await screen.findByText(/No workspace layout yet/)).toBeTruthy();
    });

    it("is closed to members who can't set it", async () => {
        mocks.can.mockImplementation(() => false);
        mocks.role = "staff";
        render(<HomeLayoutSettingsPage />);
        expect(mocks.get).not.toHaveBeenCalled();
        expect(screen.queryByRole("switch")).toBeNull();
    });
});
