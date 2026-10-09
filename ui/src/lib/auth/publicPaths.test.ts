import { describe, expect, it } from "vitest";

import { isPublicPath } from "./publicPaths";

describe("isPublicPath", () => {
  it.each(["/auth/login", "/auth/verify-email", "/invite/abc", "/embed", "/embed/widget.js", "/embed/fallcha-widget.js"])(
    "%s is public",
    (path) => expect(isPublicPath(path)).toBe(true),
  );

  it.each(["/", "/team", "/embed-admin", "/invites", "/authz"])("%s needs a session", (path) =>
    expect(isPublicPath(path)).toBe(false),
  );
});
