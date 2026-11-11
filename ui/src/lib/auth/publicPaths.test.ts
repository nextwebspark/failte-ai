import { describe, expect, it } from "vitest";

import { isPublicPath } from "./publicPaths";

describe("isPublicPath", () => {
  it.each(["/auth/login", "/auth/verify-email", "/invite/abc", "/embed", "/embed/widget.js", "/embed/lightmove-widget.js", "/embed/fallcha-widget.js", "/listen/42.abc"])(
    "%s is public",
    (path) => expect(isPublicPath(path)).toBe(true),
  );

  it.each(["/", "/team", "/embed-admin", "/invites", "/authz", "/listening"])("%s needs a session", (path) =>
    expect(isPublicPath(path)).toBe(false),
  );
});
