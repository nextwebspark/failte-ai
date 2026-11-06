import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminFeature } from "@/lib/platformAdminApi";

import FeaturesPage from "./features/page";
import PlatformAdminLayout from "./layout";

const mocks = vi.hoisted(() => ({
    isAdmin: true as boolean | null,
    features: vi.fn(),
    setPlatformFeature: vi.fn(),
    loadFlags: vi.fn(),
    auth: { loading: false, isAuthenticated: true, user: { id: "u1" } },
}));

vi.stubGlobal(
    "ResizeObserver",
    class {
        observe() {}
        unobserve() {}
        disconnect() {}
    },
);

vi.mock("next/navigation", () => ({ usePathname: () => "/superadmin/features" }));
vi.mock("@/app/skills/useSkills", () => ({ usePlatformAdmin: () => mocks.isAdmin }));
vi.mock("@/lib/auth", () => ({ useAuth: () => mocks.auth }));
vi.mock("@/lib/featureFlags", () => ({ loadFeatureFlags: mocks.loadFlags }));
vi.mock("@/lib/platformAdminApi", () => ({
    platformAdminApi: { features: mocks.features, setPlatformFeature: mocks.setPlatformFeature },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function feature(overrides: Partial<AdminFeature> = {}): AdminFeature {
    return {
        key: "campaigns",
        label: "Campaigns",
        description: "Bulk outbound calls",
        default: false,
        platform_value: null,
        effective_platform_value: false,
        overrides: [],
        ...overrides,
    };
}

describe("PlatformAdminLayout", () => {
    it("shows the tabs and the page to platform admins", () => {
        mocks.isAdmin = true;
        render(
            <PlatformAdminLayout>
                <p>Admin page</p>
            </PlatformAdminLayout>,
        );
        expect(screen.getByRole("navigation", { name: "Platform admin" })).toBeTruthy();
        expect(screen.getByRole("link", { name: "Features" }).getAttribute("aria-current")).toBe("page");
        expect(screen.getByText("Admin page")).toBeTruthy();
    });

    it("shows non-admins neither the tabs nor the page", () => {
        mocks.isAdmin = false;
        render(
            <PlatformAdminLayout>
                <p>Admin page</p>
            </PlatformAdminLayout>,
        );
        expect(screen.queryByRole("navigation", { name: "Platform admin" })).toBeNull();
        expect(screen.queryByRole("link")).toBeNull();
        expect(screen.queryByText("Admin page")).toBeNull();
        expect(screen.getByText(/This area is for platform admins only/)).toBeTruthy();
    });

    it("shows nothing but loading while the check runs", () => {
        mocks.isAdmin = null;
        render(
            <PlatformAdminLayout>
                <p>Admin page</p>
            </PlatformAdminLayout>,
        );
        expect(screen.queryByRole("navigation")).toBeNull();
        expect(screen.queryByText("Admin page")).toBeNull();
        expect(screen.getByText("Loading…")).toBeTruthy();
    });
});

describe("Platform admin features", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.features.mockResolvedValue({ features: [feature()] });
        mocks.setPlatformFeature.mockResolvedValue({ features: [feature({ platform_value: true, effective_platform_value: true })] });
    });

    it("asks before switching an area on for every workspace", async () => {
        render(<FeaturesPage />);
        fireEvent.click(await screen.findByRole("switch"));

        expect(mocks.setPlatformFeature).not.toHaveBeenCalled();
        const dialog = await screen.findByRole("alertdialog");
        expect(dialog.textContent).toContain("Turn Campaigns on for every workspace?");

        fireEvent.click(screen.getByRole("button", { name: "Turn on" }));
        await waitFor(() => expect(mocks.setPlatformFeature).toHaveBeenCalledWith("campaigns", true));
        await waitFor(() => expect(toast.success).toHaveBeenCalled());
        expect(mocks.loadFlags).toHaveBeenCalled();
        await waitFor(() => expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("true"));
    });

    it("changes nothing when the admin cancels", async () => {
        render(<FeaturesPage />);
        fireEvent.click(await screen.findByRole("switch"));
        fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));

        await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
        expect(mocks.setPlatformFeature).not.toHaveBeenCalled();
        expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("false");
    });

    it("asks before putting an area back to the default, and says what the default is", async () => {
        mocks.features.mockResolvedValue({
            features: [
                feature({
                    platform_value: true,
                    effective_platform_value: true,
                    overrides: [{ organization_id: 3, organization_name: "Bistro", enabled: false, updated_at: "" }],
                }),
            ],
        });
        render(<FeaturesPage />);
        fireEvent.click(await screen.findByRole("button", { name: "Back to the default" }));
        const dialog = await screen.findByRole("alertdialog");
        expect(dialog.textContent).toContain("back to the default (off)");
        expect(dialog.textContent).toContain("1 workspace has one and keeps it");
        fireEvent.click(screen.getByRole("button", { name: "Use the default" }));
        await waitFor(() => expect(mocks.setPlatformFeature).toHaveBeenCalledWith("campaigns", null));
    });

    it("reports a refused switch", async () => {
        mocks.setPlatformFeature.mockRejectedValue(new Error("Not allowed"));
        render(<FeaturesPage />);
        fireEvent.click(await screen.findByRole("switch"));
        fireEvent.click(await screen.findByRole("button", { name: "Turn on" }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Not allowed"));
        expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("false");
    });

    it("shows a load error with Try again, then recovers", async () => {
        mocks.features.mockRejectedValueOnce(new Error("Couldn't reach the server"));
        render(<FeaturesPage />);
        expect((await screen.findByRole("alert")).textContent).toContain("Couldn't reach the server");
        fireEvent.click(screen.getByRole("button", { name: "Try again" }));
        expect(await screen.findByRole("switch")).toBeTruthy();
    });

    it("links each workspace override to its workspace", async () => {
        mocks.features.mockResolvedValue({
            features: [feature({ overrides: [{ organization_id: 3, organization_name: "Bistro", enabled: true, updated_at: "" }] })],
        });
        render(<FeaturesPage />);
        expect((await screen.findByRole("link", { name: "Bistro" })).getAttribute("href")).toBe("/superadmin/organizations/3");
    });
});
