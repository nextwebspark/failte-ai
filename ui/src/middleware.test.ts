import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The middleware module caches the backend's answers, so each test loads a
// fresh copy.
async function loadMiddleware() {
    vi.resetModules();
    return (await import("./middleware")).middleware;
}

function respond(features: unknown, ok = true) {
    return { ok, json: async () => features } as Response;
}

describe("middleware feature redirects", () => {
    const fetchMock = vi.fn();

    beforeEach(() => {
        fetchMock.mockReset();
        vi.stubGlobal("fetch", fetchMock);
    });
    afterEach(() => vi.unstubAllGlobals());

    function route(url: string, features: unknown, ok = true) {
        fetchMock.mockImplementation(async (input: string) => {
            if (input.endsWith("/api/v1/features/public")) return respond(features, ok);
            // /api/v1/health: report Stack auth so the local sign-in guard stays out of the way.
            return respond({ auth_provider: "stack" });
        });
        return new NextRequest(new URL(url, "http://app.test"));
    }

    it("sends an area that is off for everyone to Overview", async () => {
        const middleware = await loadMiddleware();
        const response = await middleware(route("/campaigns/new", { features: { campaigns: false, skills: false } }));
        expect(response.status).toBe(307);
        expect(response.headers.get("location")).toBe("http://app.test/overview");
    });

    it("lets an area through when it is on for some workspace", async () => {
        const middleware = await loadMiddleware();
        const response = await middleware(route("/skills", { features: { campaigns: false, skills: true } }));
        expect(response.headers.get("location")).toBeNull();
    });

    it("falls back to the defaults (off) when the backend can't answer", async () => {
        const middleware = await loadMiddleware();
        const response = await middleware(route("/campaigns", { detail: "error" }, false));
        expect(response.headers.get("location")).toBe("http://app.test/overview");
    });

    it("does not ask about features for other pages", async () => {
        const middleware = await loadMiddleware();
        await middleware(route("/workflow", { features: {} }));
        const urls = fetchMock.mock.calls.map(([input]) => String(input));
        expect(urls.some((url) => url.endsWith("/api/v1/features/public"))).toBe(false);
    });

    it("caches the answer briefly", async () => {
        const middleware = await loadMiddleware();
        await middleware(route("/skills", { features: { skills: true } }));
        await middleware(route("/skills/new", { features: { skills: true } }));
        const featureCalls = fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/api/v1/features/public"));
        expect(featureCalls).toHaveLength(1);
    });
});
