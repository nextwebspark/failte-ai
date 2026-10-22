import { afterEach, describe, expect, it, vi } from "vitest";

import { clearOAuthPopupMarker, handOffOAuthReturn, listenForOAuthReturn, markOAuthPopup } from "./oauthPopup";

const RETURN = "?integration_result=success&connection_id=0b6f1f0e-1c1a-4d3e-9a55-5f6c7e8d9a0b&provider=google-calendar";

afterEach(() => {
    clearOAuthPopupMarker();
    vi.restoreAllMocks();
    window.history.replaceState(null, "", "/");
});

describe("handing a pop-up sign-in back", () => {
    it("broadcasts the return to the waiting screen and closes the pop-up", async () => {
        const received = new Promise<URLSearchParams>((resolve) => {
            const stop = listenForOAuthReturn((params) => {
                stop();
                resolve(params);
            });
        });
        const close = vi.spyOn(window, "close").mockImplementation(() => {});
        markOAuthPopup("google-calendar");
        window.history.replaceState(null, "", `/integrations${RETURN}`);

        expect(handOffOAuthReturn()).toBe(true);
        expect(close).toHaveBeenCalled();
        expect((await received).get("connection_id")).toBe("0b6f1f0e-1c1a-4d3e-9a55-5f6c7e8d9a0b");
        // Used once: a later visit finishes on /integrations as usual.
        expect(handOffOAuthReturn()).toBe(false);
    });

    it("hands over a failed sign-in too", () => {
        vi.spyOn(window, "close").mockImplementation(() => {});
        markOAuthPopup("google-calendar");
        window.history.replaceState(null, "", "/integrations?integration_result=error&reason=access_denied");
        expect(handOffOAuthReturn()).toBe(true);
    });

    it("leaves an ordinary /integrations sign-in alone", () => {
        window.history.replaceState(null, "", `/integrations${RETURN}`);
        expect(handOffOAuthReturn()).toBe(false); // nobody waiting

        markOAuthPopup("hubspot");
        expect(handOffOAuthReturn()).toBe(false); // waiting for another provider

        markOAuthPopup("google-calendar", Date.now() - 11 * 60 * 1000);
        expect(handOffOAuthReturn()).toBe(false); // stale

        markOAuthPopup("google-calendar");
        window.history.replaceState(null, "", "/integrations");
        expect(handOffOAuthReturn()).toBe(false); // no return in the URL
    });
});
