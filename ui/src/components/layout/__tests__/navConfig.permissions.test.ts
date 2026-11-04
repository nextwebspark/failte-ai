import { describe, expect, it } from "vitest";

import { getRequiredPermission, NAV_SECTIONS } from "../navConfig";

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
