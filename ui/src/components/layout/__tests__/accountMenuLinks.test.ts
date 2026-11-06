import { describe, expect, it } from "vitest";

import type { Permission } from "@/lib/auth/roles";

import { accountMenuLinks } from "../AppTopBar";

const ROLES: Record<string, Permission[]> = {
    admin: ["org:manage", "members:read", "members:manage", "billing:read", "calls:read", "integrations:read"],
    owner: ["agents:read", "calls:read", "reports:read", "bookings:manage", "bookings:grant", "agents:facts", "notifications:manage"],
    staff: ["agents:read", "calls:read", "reports:read"],
    nothing: [],
};

const canFor = (role: string) => (...required: Permission[]) => required.every((p) => ROLES[role].includes(p));
const labels = (role: string, provider = "local") => accountMenuLinks(provider, canFor(role)).map((l) => l.label);

describe("accountMenuLinks", () => {
    it("gives an admin Team and Settings", () => {
        expect(labels("admin")).toEqual(["Your account", "Team", "Settings"]);
        const settings = accountMenuLinks("local", canFor("admin")).find((l) => l.label === "Settings");
        expect(settings?.href).toBe("/settings");
    });

    it("hides Team from the owner and staff, who can't see members", () => {
        expect(labels("owner")).not.toContain("Team");
        expect(labels("staff")).not.toContain("Team");
    });

    it("sends the owner's Settings to the first screen they can open", () => {
        const settings = accountMenuLinks("local", canFor("owner")).find((l) => l.label === "Settings");
        expect(settings?.href).toBe("/settings/notifications");
    });

    it("drops Settings when it would only repeat Your account", () => {
        expect(labels("nothing")).toEqual(["Your account"]);
    });

    it("shows only the always-open links while the role loads", () => {
        expect(accountMenuLinks("local", null).map((l) => l.label)).toEqual(["Your account"]);
    });

    it("adds Account settings for hosted sign-in", () => {
        expect(labels("staff", "stack")[0]).toBe("Account settings");
        expect(labels("staff", "local")).not.toContain("Account settings");
    });

    it("gives every link a real path", () => {
        for (const link of accountMenuLinks("stack", canFor("admin"))) {
            expect(link.href.startsWith("/")).toBe(true);
        }
    });
});
