import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { isSafeNextPath, startLocalSession } from "./localSession";

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

describe("startLocalSession", () => {
  const auth = { token: "tok", user: { id: 1 } };
  const replace = vi.fn();
  const realLocation = Object.getOwnPropertyDescriptor(window, "location")!;

  beforeEach(() => {
    replace.mockReset();
    Object.defineProperty(window, "location", { configurable: true, value: { replace } });
  });

  afterEach(() => {
    Object.defineProperty(window, "location", realLocation);
    vi.unstubAllGlobals();
  });

  /** Settles within a tick, or reports "pending". */
  function settled(promise: Promise<unknown>): Promise<string> {
    return Promise.race([
      promise.then(
        () => "resolved",
        () => "rejected",
      ),
      new Promise<string>((done) => setTimeout(() => done("pending"), 20)),
    ]);
  }

  it("stores the session, replaces the page with /after-sign-in and never resolves", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);

    expect(await settled(startLocalSession(auth))).toBe("pending");
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/session", expect.objectContaining({ method: "POST" }));
    expect(replace).toHaveBeenCalledWith("/after-sign-in");
  });

  it("goes to a safe next path, ignoring an unsafe one", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true }));
    void startLocalSession(auth, "/team");
    void startLocalSession(auth, "//evil.example");
    await vi.waitFor(() => expect(replace).toHaveBeenCalledTimes(2));
    expect(replace.mock.calls).toEqual([["/team"], ["/after-sign-in"]]);
  });

  it("rejects without navigating when the session can't be stored", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
    expect(await settled(startLocalSession(auth))).toBe("rejected");
    expect(replace).not.toHaveBeenCalled();
  });
});
