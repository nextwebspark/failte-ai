import { afterEach, describe, expect, it, vi } from "vitest";

import { forgetReconnect, rememberReconnect, takeReconnect } from "./reconnect";

const OLD_ID = "4f1c2d3e-5a6b-4c7d-8e9f-0a1b2c3d4e5f";

afterEach(() => {
    forgetReconnect();
    vi.restoreAllMocks();
});

describe("reconnect memory", () => {
    it("returns the remembered connection for the same provider, once", () => {
        rememberReconnect({ provider: "google-calendar", oldConnectionId: OLD_ID }, 1_000);
        expect(takeReconnect("google-calendar", 2_000)).toEqual({ provider: "google-calendar", oldConnectionId: OLD_ID });
        expect(takeReconnect("google-calendar", 2_000)).toBeNull();
    });

    it("ignores another provider and still clears the entry", () => {
        rememberReconnect({ provider: "google-calendar", oldConnectionId: OLD_ID }, 1_000);
        expect(takeReconnect("google-sheets", 2_000)).toBeNull();
        expect(takeReconnect("google-calendar", 2_000)).toBeNull();
    });

    it("expires after the OAuth flow lifetime", () => {
        rememberReconnect({ provider: "google-calendar", oldConnectionId: OLD_ID }, 0);
        expect(takeReconnect("google-calendar", 11 * 60 * 1000)).toBeNull();
    });

    it("tolerates blocked or corrupt storage", () => {
        window.sessionStorage.setItem("fallcha.integrations.reconnect", "{oops");
        expect(takeReconnect("google-calendar")).toBeNull();

        vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
            throw new Error("blocked");
        });
        vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
            throw new Error("blocked");
        });
        expect(() => rememberReconnect({ provider: "google-calendar", oldConnectionId: OLD_ID })).not.toThrow();
        expect(takeReconnect("google-calendar")).toBeNull();
    });
});
