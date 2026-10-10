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
  ])("%s requires %s", (path, permission) => {
    expect(getRequiredPermission(path)).toBe(permission);
  });

  it.each(["/overview", "/after-sign-in", "/workflows-archive-lookalike"])(
    "%s is open to every member",
    (path) => {
      expect(getRequiredPermission(path)).toBeNull();
    },
  );

  it("does not match sibling routes sharing a prefix", () => {
    expect(getRequiredPermission("/teams-of-agents")).toBeNull();
  });

  it("lists Team for everyone and gates build tools", () => {
    const items = NAV_SECTIONS.flatMap((section) => section.items);
    expect(items.find((item) => item.url === "/team")?.requires).toBe("members:read");
    expect(items.find((item) => item.url === "/tools")?.requires).toBe("agents:write");
  });
});
