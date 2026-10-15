import { afterEach, describe, expect, it, vi } from "vitest";

import { clearPendingOAuth, PENDING_OAUTH_TTL_MS, rememberPendingOAuth, takePendingOAuth } from "./pendingOAuth";

const OLD_ID = "4f1c2d3e-5a6b-4c7d-8e9f-0a1b2c3d4e5f";

afterEach(() => {
    window.sessionStorage.clear();
    vi.restoreAllMocks();
});

describe("pending OAuth memory", () => {
    it("returns the entry for its provider once", () => {
        rememberPendingOAuth("google-calendar", { nonce: "n1", replacesConnectionId: OLD_ID }, 1_000);
        expect(takePendingOAuth("google-calendar", 2_000)).toEqual({ nonce: "n1", replacesConnectionId: OLD_ID });
        expect(takePendingOAuth("google-calendar", 2_000)).toBeNull();
    });

    it("keys entries by provider", () => {
        rememberPendingOAuth("google-calendar", { nonce: "cal" }, 0);
        rememberPendingOAuth("google-sheets", { nonce: "sheets" }, 0);
        expect(takePendingOAuth("google-sheets", 1)).toEqual({ nonce: "sheets" });
        expect(takePendingOAuth("google-calendar", 1)).toEqual({ nonce: "cal" });
    });

    it("expires with the OAuth flow", () => {
        rememberPendingOAuth("google-calendar", { nonce: "n1" }, 0);
        expect(takePendingOAuth("google-calendar", PENDING_OAUTH_TTL_MS + 1)).toBeNull();
        expect(window.sessionStorage.length).toBe(0);
    });

    it("clears every entry, or one provider's", () => {
        rememberPendingOAuth("google-calendar", { nonce: "a" });
        rememberPendingOAuth("google-sheets", { nonce: "b" });
        window.sessionStorage.setItem("unrelated", "keep");
        clearPendingOAuth("google-sheets");
        expect(window.sessionStorage.length).toBe(2);
        clearPendingOAuth();
        expect(window.sessionStorage.length).toBe(1);
        expect(window.sessionStorage.getItem("unrelated")).toBe("keep");
    });

    it("tolerates corrupt or blocked storage", () => {
        window.sessionStorage.setItem("fallcha.integrations.oauth.google-calendar", "{oops");
        expect(takePendingOAuth("google-calendar")).toBeNull();
        window.sessionStorage.setItem("fallcha.integrations.oauth.google-calendar", JSON.stringify({ savedAt: 1 }));
        expect(takePendingOAuth("google-calendar")).toBeNull();

        vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
            throw new Error("blocked");
        });
        vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
            throw new Error("blocked");
        });
        expect(() => rememberPendingOAuth("google-calendar", { nonce: "n" })).not.toThrow();
        expect(takePendingOAuth("google-calendar")).toBeNull();
    });
});
