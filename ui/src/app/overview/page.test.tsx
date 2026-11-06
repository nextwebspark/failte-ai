import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import OverviewPage from "./page";

const ROLE_PERMISSIONS: Record<string, string[]> = {
    admin: [
        "agents:read",
        "agents:write",
        "calls:read",
        "reports:read",
        "credentials:write",
        "integrations:read",
        "integrations:write",
        "members:read",
    ],
    owner: ["agents:read", "calls:read", "reports:read", "bookings:manage", "bookings:grant", "agents:facts", "notifications:manage"],
    staff: ["agents:read", "calls:read", "reports:read"],
    none: [],
};

const mocks = vi.hoisted(() => ({
    perms: [] as string[],
    displayName: "Mary Byrne" as string | null,
}));

vi.mock("@/context/OrgConfigContext", () => ({
    useOrgConfig: () => ({ can: (...required: string[]) => required.every((p) => mocks.perms.includes(p)) }),
}));
vi.mock("@/lib/auth", () => ({
    useAuth: () => ({ user: { displayName: mocks.displayName }, provider: "stack" }),
}));
vi.mock("@/components/SupportLink", () => ({
    SupportLink: ({ label }: { label: string }) => <a href="mailto:help@example.com">{label}</a>,
}));

function hrefs(): string[] {
    return screen.getAllByRole("link").map((a) => a.getAttribute("href") ?? "");
}

describe("OverviewPage", () => {
    beforeEach(() => {
        mocks.perms = ROLE_PERMISSIONS.admin;
        mocks.displayName = "Mary Byrne";
    });

    it("greets the person by first name", () => {
        render(<OverviewPage />);
        expect(screen.getByRole("heading", { level: 1 }).textContent).toMatch(
            /^Good (morning|afternoon|evening), Mary$/,
        );
    });

    it("gives an admin the daily links and the set-up links", () => {
        render(<OverviewPage />);
        const links = hrefs();
        for (const href of ["/usage", "/bookings", "/reports", "/workflow", "/workflow/create", "/model-configurations"]) {
            expect(links).toContain(href);
        }
        expect(screen.getByText("Choose your agent's voice and language.")).toBeTruthy();
    });

    it("gives the owner Calls, Bookings, Reports and agents, and nothing they can't open", () => {
        mocks.perms = ROLE_PERMISSIONS.owner;
        render(<OverviewPage />);

        const daily = screen.getByRole("region", { name: "Day to day" });
        const names = within(daily)
            .getAllByRole("link")
            .map((a) => a.textContent);
        expect(names.some((n) => n?.startsWith("Calls"))).toBe(true);
        expect(names.some((n) => n?.startsWith("Bookings"))).toBe(true);
        expect(names.some((n) => n?.startsWith("Reports"))).toBe(true);
        expect(names.some((n) => n?.startsWith("Your agents"))).toBe(true);

        expect(hrefs()).not.toContain("/workflow/create");
        expect(hrefs()).not.toContain("/model-configurations");
        expect(screen.queryByRole("region", { name: "Set up" })).toBeNull();
    });

    it("gives staff the same day-to-day links, without set-up", () => {
        mocks.perms = ROLE_PERMISSIONS.staff;
        render(<OverviewPage />);
        expect(hrefs()).toEqual(expect.arrayContaining(["/usage", "/bookings", "/reports", "/workflow"]));
        expect(hrefs()).not.toContain("/model-configurations");
    });

    it("shows only help to someone whose role has not loaded or grants nothing", () => {
        mocks.perms = ROLE_PERMISSIONS.none;
        render(<OverviewPage />);
        expect(hrefs()).toEqual(["mailto:help@example.com"]);
        expect(screen.queryByRole("region", { name: "Day to day" })).toBeNull();
    });

    it("uses no technical jargon", () => {
        const { container } = render(<OverviewPage />);
        expect(container.textContent).not.toMatch(/LLM|TTS|STT|provider/);
    });

    it("makes each card one real link, with no nested buttons", () => {
        render(<OverviewPage />);
        const calls = screen.getByRole("link", { name: /^Calls/ });
        expect(calls.getAttribute("href")).toBe("/usage");
        expect(calls.querySelector("a, button")).toBeNull();
    });
});
