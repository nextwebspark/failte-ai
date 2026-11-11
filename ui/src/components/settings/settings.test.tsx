import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Permission } from "@/lib/auth/roles";

import {
  firstSettingsUrl,
  isSettingsRoute,
  SETTINGS_ROUTE_PERMISSIONS,
  settingsItemFor,
  visibleSettingsSections,
} from "./settingsNav";
import { SettingsShell } from "./SettingsShell";

const mocks = vi.hoisted(() => ({
  pathname: "/settings/compliance",
  permissions: new Set<string>(),
  role: "viewer" as string | null,
}));

vi.mock("next/navigation", () => ({ usePathname: () => mocks.pathname }));

vi.mock("@/context/OrgConfigContext", () => ({
  useOrgConfig: () => ({
    role: mocks.role,
    can: (permission: string) => mocks.permissions.has(permission),
  }),
}));

const VIEWER: Permission[] = [
  "members:read",
  "billing:read",
  "agents:read",
  "campaigns:read",
  "calls:read",
  "reports:read",
];
const viewerCan = (permission: Permission) => VIEWER.includes(permission);

describe("settings menu", () => {
  it("names the screen a route is on, longest match first", () => {
    expect(settingsItemFor("/settings")?.title).toBe("General");
    expect(settingsItemFor("/settings/compliance")?.title).toBe("Privacy & compliance");
    expect(settingsItemFor("/team")?.title).toBe("Members");
    expect(settingsItemFor("/workflow/3/settings")).toBeNull();
    expect(isSettingsRoute("/teams-of-agents")).toBe(false);
  });

  it("shows a client only the screens their role can open", () => {
    const titles = visibleSettingsSections(viewerCan).flatMap((s) => s.items.map((i) => i.title));
    expect(titles).toEqual(["Members", "Reports by email", "Billing", "Privacy & compliance", "Your account"]);
    expect(firstSettingsUrl(viewerCan)).toBe("/team");
  });

  it("lists everything while the role is still loading", () => {
    expect(firstSettingsUrl(null)).toBe("/settings");
    expect(visibleSettingsSections(null).map((s) => s.label)).toEqual([
      "Workspace",
      "Compliance",
      "Developer",
      "Account",
    ]);
  });

  it("keeps the old screens' permissions and leaves General to redirect", () => {
    expect(SETTINGS_ROUTE_PERMISSIONS).toMatchObject({
      "/team": "members:read",
      "/billing": "billing:read",
      "/api-keys": "api_keys:manage",
      "/settings/developer": "integrations:read",
    });
    expect(SETTINGS_ROUTE_PERMISSIONS).not.toHaveProperty("/settings");
    expect(SETTINGS_ROUTE_PERMISSIONS).not.toHaveProperty("/account");
  });
});

describe("SettingsShell", () => {
  beforeEach(() => {
    mocks.pathname = "/settings/compliance";
    mocks.role = "viewer";
    mocks.permissions = new Set(VIEWER);
  });

  it("opens with the screen's title and description, and marks it in the menu", () => {
    render(
      <SettingsShell>
        <p>content</p>
      </SettingsShell>,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Privacy & compliance" })).toBeTruthy();
    expect(screen.getByText(/How long call data is kept/)).toBeTruthy();
    const current = screen.getByRole("link", { current: "page" });
    expect(current.textContent).toBe("Privacy & compliance");
    expect(screen.getByText("content")).toBeTruthy();
  });

  it("hides screens the role cannot open", () => {
    render(<SettingsShell>{null}</SettingsShell>);
    const nav = screen.getByRole("navigation", { name: "Settings" });
    expect(nav.textContent).not.toContain("API keys");
    expect(nav.textContent).not.toContain("General");
    expect(nav.textContent).toContain("Your account");
  });
});
