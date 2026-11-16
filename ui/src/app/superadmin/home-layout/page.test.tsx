import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PlatformHomeLayout } from "@/lib/platformAdminApi";

import HomeLayoutPage from "./page";

const mocks = vi.hoisted(() => ({
    homeLayout: vi.fn(),
    setHomeLayout: vi.fn(),
    auth: { loading: false, isAuthenticated: true, user: { id: "u1" } },
}));

vi.mock("@/lib/auth", () => ({ useAuth: () => mocks.auth }));
vi.mock("@/lib/platformAdminApi", () => ({
    platformAdminApi: { homeLayout: mocks.homeLayout, setHomeLayout: mocks.setHomeLayout },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const CARDS = [
    { id: "tiles", label: "Call numbers" },
    { id: "attention", label: "Needs your attention" },
    { id: "recent-calls", label: "Recent calls" },
];

function response(layout: PlatformHomeLayout["layout"]): PlatformHomeLayout {
    return { layout, built_in: { hidden: [], pinned: [] }, cards: CARDS };
}

describe("Platform admin Home layout", () => {
    beforeEach(() => {
        mocks.homeLayout.mockReset();
        mocks.setHomeLayout.mockReset();
    });

    it("starts from the built-in layout and saves which cards show", async () => {
        mocks.homeLayout.mockResolvedValue(response(null));
        mocks.setHomeLayout.mockImplementation(async (layout) => response(layout));
        render(<HomeLayoutPage />);
        const tiles = await screen.findByRole("switch", { name: "Call numbers" });
        expect(tiles.getAttribute("aria-checked")).toBe("true");
        expect(screen.getByRole("switch", { name: "Recent calls" }).getAttribute("aria-checked")).toBe("true");
        expect(screen.getByText(/built-in layout applies/)).toBeTruthy();
        expect(screen.queryByRole("button", { name: "Use the built-in layout" })).toBeNull();

        fireEvent.click(screen.getByRole("switch", { name: "Recent calls" }));
        fireEvent.click(screen.getByRole("button", { name: "Save" }));
        await waitFor(() =>
            expect(mocks.setHomeLayout).toHaveBeenCalledWith({ hidden: ["recent-calls"], pinned: [] }),
        );
        expect(await screen.findByText("A platform admin set this layout.")).toBeTruthy();
    });

    it("offers a calm first visit as a preset", async () => {
        mocks.homeLayout.mockResolvedValue(response(null));
        mocks.setHomeLayout.mockImplementation(async (layout) => response(layout));
        render(<HomeLayoutPage />);
        fireEvent.click(await screen.findByRole("button", { name: "Calm first visit" }));
        await waitFor(() =>
            expect(mocks.setHomeLayout).toHaveBeenCalledWith({
                hidden: ["tiles", "callers-wanted", "when-called", "quick-links"],
                pinned: [],
            }),
        );
    });

    it("goes back to the built-in layout", async () => {
        mocks.homeLayout.mockResolvedValue(response({ hidden: [], pinned: [] }));
        mocks.setHomeLayout.mockResolvedValue(response(null));
        render(<HomeLayoutPage />);
        fireEvent.click(await screen.findByRole("button", { name: "Use the built-in layout" }));
        await waitFor(() => expect(mocks.setHomeLayout).toHaveBeenCalledWith(null));
    });
});
