import { describe, expect, it } from "vitest";

import { isSafeNextPath } from "./localSession";

describe("isSafeNextPath", () => {
  it.each(["/workflow", "/settings/team?tab=1"])("accepts same-origin path %s", (path) => {
    expect(isSafeNextPath(path)).toBe(true);
  });

  it.each([
    null,
    undefined,
    "",
    "https://evil.example",
    "//evil.example",
    "/\\evil.example",
    "/\t/evil.example",
    "/\n/evil.example",
    "/\u007f/evil.example",
    "workflow",
  ])(
    "rejects %s",
    (path) => {
      expect(isSafeNextPath(path)).toBe(false);
    },
  );
});
