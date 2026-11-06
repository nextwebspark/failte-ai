import { describe, expect, it } from "vitest";

import { agentRowHref, getPageMeta, getRequiredPermission, NAV_SECTIONS } from "../navConfig";

describe("getRequiredPermission", () => {
  it.each([
    ["/telephony-configurations", "telephony:read"],
    ["/telephony-configurations/12", "telephony:read"],
    ["/workflow", "agents:read"],
    ["/workflow/42/run/7", "agents:read"],
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

  it("folds Team, Billing and Developers into one Settings row", () => {
    const items = NAV_SECTIONS.flatMap((section) => section.items);
    expect(items.find((item) => item.settingsHub)?.url).toBe("/settings");
    for (const moved of ["/team", "/billing", "/api-keys"]) {
      expect(items.some((item) => item.url === moved)).toBe(false);
    }
    expect(items.find((item) => item.url === "/tools")?.requires).toBe("agents:write");
  });
});

describe("the redesigned nav", () => {
  it("has the owner's screens, Your agent and one Advanced setup group", () => {
    expect(NAV_SECTIONS.map((section) => [section.id, section.label ?? null, Boolean(section.collapsible)])).toEqual([
      ["main", null, false],
      ["agent", "Your agent", false],
      ["advanced", "Advanced setup", true],
    ]);
    expect(NAV_SECTIONS[0].items.map((item) => item.title)).toEqual(["Home", "Calls", "Follow-ups", "Bookings", "Reports"]);
    expect(NAV_SECTIONS[1].items.map((item) => item.title)).toEqual(["What your agent knows", "Phone number", "Settings"]);
  });

  it("names the dashboard Home in the breadcrumb", () => {
    expect(getPageMeta("/overview").title).toBe("Home");
    expect(getPageMeta("/follow-ups").title).toBe("Follow-ups");
  });

  it("does not guard the agents list with a Your agent row's fallback address", () => {
    // "What your agent knows" falls back to /workflow; that must not change
    // what /workflow itself needs.
    expect(getRequiredPermission("/workflow")).toBe("agents:read");
    expect(getRequiredPermission("/telephony-configurations")).toBe("telephony:read");
  });
});

describe("agentRowHref", () => {
  const all = () => true;
  const owner = (p: string) => p === "agents:read";

  it("goes straight to the one agent", () => {
    expect(agentRowHref("facts", [{ id: 7 }], all)).toBe("/workflow/7/facts");
    expect(agentRowHref("phone", [{ id: 7 }], owner)).toBe("/workflow/7/deployment#phone");
  });

  it("starts someone who can build on creating an agent when there is none", () => {
    expect(agentRowHref("facts", [], all)).toBe("/workflow/create");
    expect(agentRowHref("facts", [], owner)).toBe("/workflow");
  });

  it("lists the agents when there are several, or while they load", () => {
    expect(agentRowHref("facts", [{ id: 1 }, { id: 2 }], all)).toBe("/workflow");
    expect(agentRowHref("facts", null, all)).toBe("/workflow");
    expect(agentRowHref("phone", [{ id: 1 }, { id: 2 }], all)).toBe("/telephony-configurations");
    expect(agentRowHref("phone", [{ id: 1 }, { id: 2 }], owner)).toBe("/workflow");
  });
});
