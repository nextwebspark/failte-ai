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

  it("gives Team and Billing their own rows, and folds the rest of Settings into one", () => {
    const items = NAV_SECTIONS.flatMap((section) => section.items);
    expect(items.find((item) => item.settingsHub)?.url).toBe("/settings");
    expect(items.find((item) => item.url === "/team")?.requires).toBe("members:read");
    expect(items.find((item) => item.url === "/billing")?.requires).toBe("billing:read");
    expect(items.some((item) => item.url === "/api-keys")).toBe(false);
    expect(items.find((item) => item.url === "/tools")?.requires).toBe("agents:write");
  });
});

describe("the one menu", () => {
  it("has the business, the agent, and the workspace, with the builder screens folded away", () => {
    expect(NAV_SECTIONS.map((section) => [section.id, section.label ?? null, Boolean(section.collapsible)])).toEqual([
      ["main", null, false],
      ["agent", "Agent", false],
      ["agent-advanced", "Advanced", true],
      ["workspace", "Workspace", false],
      ["advanced", "Advanced setup", true],
    ]);
    const titles = (id: string) => NAV_SECTIONS.find((s) => s.id === id)!.items.map((item) => item.title);
    expect(titles("main")).toEqual(["Home", "Calls", "Follow-ups", "Bookings", "Reports"]);
    expect(titles("agent")).toEqual(["What your agent knows", "Phone number"]);
    expect(titles("agent-advanced")).toEqual(["Conversation", "Model and voice", "Advanced settings"]);
    expect(titles("workspace")).toEqual(["Voice agents", "Team", "Billing", "Settings"]);
    expect(titles("advanced")).toEqual([
      "Integrations",
      "Tools",
      "Files",
      "Telephony",
      "Models & voice",
      "Prompt audio",
    ]);
  });

  it("keeps every row as strict as its screen", () => {
    const items = NAV_SECTIONS.flatMap((section) => section.items);
    const requires = (title: string) => items.find((item) => item.title === title)?.requires;
    expect(requires("Model and voice")).toBe("agents:write");
    expect(requires("Advanced settings")).toBe("agents:write");
    expect(requires("Conversation")).toBe("agents:read");
    expect(requires("What your agent knows")).toBe("agents:read");
    expect(requires("Models & voice")).toBe("credentials:write");
    expect(requires("Telephony")).toBe("telephony:read");
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
