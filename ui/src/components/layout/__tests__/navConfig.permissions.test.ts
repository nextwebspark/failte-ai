import { describe, expect, it } from "vitest";

import { getPageMeta, getRequiredPermission, NAV_SECTIONS } from "../navConfig";

describe("getRequiredPermission", () => {
  it.each([
    ["/telephony-configurations", "telephony:read"],
    ["/telephony-configurations/12", "telephony:read"],
    ["/workflow", "agents:read"],
    ["/workflow/42/run/7", "agents:read"],
    ["/workflow/42/facts", "agents:read"],
    ["/workflow/42/deployment", "agents:read"],
    ["/workflow/42/settings", "agents:write"],
    ["/workflow/42/model", "agents:write"],
    ["/workflow/create", "agents:write"],
    ["/campaigns/new", "campaigns:write"],
    ["/api-keys", "api_keys:manage"],
    ["/team", "members:read"],
    ["/integrations", "integrations:read"],
    ["/skills", "agents:read"],
    ["/skills/abc-123", "agents:read"],
    ["/skills/library/abc-123", "agents:read"],
    ["/skills/new", "agents:write"],
    ["/billing", "billing:read"],
    ["/settings/compliance", "calls:read"],
    ["/settings/developer", "integrations:read"],
    ["/follow-ups", "calls:read"],
    ["/usage", "reports:read"],
  ])("%s requires %s", (path, permission) => {
    expect(getRequiredPermission(path)).toBe(permission);
  });

  it.each(["/overview", "/after-sign-in", "/workflows-archive-lookalike", "/settings", "/account"])(
    "%s is open to every member",
    (path) => {
      expect(getRequiredPermission(path)).toBeNull();
    },
  );

  it("does not match sibling routes sharing a prefix", () => {
    expect(getRequiredPermission("/teams-of-agents")).toBeNull();
  });

  it("puts Team, Billing and the phone and AI setup under Settings", () => {
    const items = NAV_SECTIONS.flatMap((section) => section.items);
    expect(items.find((item) => item.settingsHub)?.url).toBe("/settings");
    for (const url of ["/team", "/billing", "/api-keys", "/tools", "/files", "/telephony-configurations", "/recordings"]) {
      expect(items.some((item) => item.url === url)).toBe(false);
    }
    // Their screens stay as strict as before.
    expect(getRequiredPermission("/tools")).toBe("agents:write");
    expect(getRequiredPermission("/tools/abc")).toBe("agents:write");
    expect(getRequiredPermission("/files")).toBe("agents:write");
    expect(getRequiredPermission("/recordings")).toBe("agents:write");
    expect(getRequiredPermission("/model-configurations")).toBe("credentials:write");
  });
});

describe("the one menu", () => {
  it("has the business, the agent and the workspace, with nothing folded away", () => {
    expect(NAV_SECTIONS.map((section) => [section.id, section.label ?? null])).toEqual([
      ["main", null],
      ["agent", "Your agent"],
      ["workspace", "Workspace"],
    ]);
    const titles = (id: string) => NAV_SECTIONS.find((s) => s.id === id)!.items.map((item) => item.title);
    expect(titles("main")).toEqual(["Home", "Calls", "Follow-ups", "Bookings", "Reports"]);
    expect(titles("agent")).toEqual([
      "What your agent knows",
      "Phone number",
      "Voice & model",
      "Call flow",
      "Agent settings",
    ]);
    // Campaigns and Skills are switched off by default.
    expect(titles("workspace")).toEqual(["Voice agents", "Integrations", "Settings"]);
  });

  it("keeps every row as strict as its screen", () => {
    const items = NAV_SECTIONS.flatMap((section) => section.items);
    const requires = (title: string) => items.find((item) => item.title === title)?.requires;
    expect(requires("Voice & model")).toBe("agents:write");
    expect(requires("Agent settings")).toBe("agents:write");
    expect(requires("Call flow")).toBe("agents:read");
    expect(requires("What your agent knows")).toBe("agents:read");
    expect(requires("Integrations")).toBe("integrations:read");
  });

  it("names the dashboard Home in the breadcrumb", () => {
    expect(getPageMeta("/overview").title).toBe("Home");
    expect(getPageMeta("/follow-ups").title).toBe("Follow-ups");
  });

  it("does not guard the agents list with an Agent row's fallback address", () => {
    // The Agent rows fall back to /workflow while agents load; that must not
    // change what /workflow itself needs.
    expect(getRequiredPermission("/workflow")).toBe("agents:read");
    expect(getRequiredPermission("/telephony-configurations")).toBe("telephony:read");
  });
});
