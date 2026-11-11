import { describe, expect, it } from "vitest";

import { isNavRowActive, isWithin } from "../navConfig";

describe("isNavRowActive", () => {
  it.each([
    ["/tools", "/tools"],
    ["/tools", "/tools/abc-123"],
    ["/telephony-configurations", "/telephony-configurations/7"],
    ["/skills", "/skills/library/3"],
    ["/workflow", "/workflow/create"],
    ["/campaigns", "/campaigns/12/edit"],
  ])("lights %s on %s", (url, pathname) => {
    expect(isNavRowActive(url, pathname)).toBe(true);
  });

  it("does not light a row whose name only starts the same", () => {
    expect(isWithin("/toolsets", "/tools")).toBe(false);
    expect(isNavRowActive("/tools", "/toolsets")).toBe(false);
    expect(isNavRowActive("/usage", "/overview")).toBe(false);
  });

  it("keeps the list a run was opened from lit, query string and all", () => {
    expect(isNavRowActive("/usage", "/workflow/1/run/9", "/usage?page=2&status=done")).toBe(true);
    expect(isNavRowActive("/workflow", "/workflow/1/run/9", "/usage?page=2")).toBe(true);
    expect(isNavRowActive("/reports", "/workflow/1/run/9", "/usage")).toBe(false);
  });
});
