import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/** The 401 handler: confirm with /auth/me once, then end the session. */
describe("session ended handling", () => {
    let responseInterceptor: (response: Response, request: Request) => Promise<Response>;

    beforeEach(async () => {
        vi.resetModules();
        const { setupAuthInterceptor } = await import("./apiClient");
        const client = {
            interceptors: {
                request: { use: vi.fn() },
                response: { use: vi.fn((fn) => (responseInterceptor = fn)) },
            },
        };
        onEnded = vi.fn<() => void>();
        setupAuthInterceptor(client as never, async () => "stale-token", onEnded);
    });
    afterEach(() => vi.unstubAllGlobals());

    let onEnded: ReturnType<typeof vi.fn<() => void>>;
    const req = (path: string) => new Request(`http://localhost:8000${path}`);

    it("signs out when /auth/me also rejects the session", async () => {
        const fetchMock = vi.fn<typeof fetch>(async () => new Response(null, { status: 401 }));
        vi.stubGlobal("fetch", fetchMock);
        await responseInterceptor(new Response(null, { status: 401 }), req("/api/v1/organizations"));
        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(String(fetchMock.mock.calls[0][0])).toBe("http://localhost:8000/api/v1/auth/me");
        expect(onEnded).toHaveBeenCalledTimes(1);
    });

    it("keeps the session when /auth/me says it is fine", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
        await responseInterceptor(new Response(null, { status: 401 }), req("/api/v1/features"));
        expect(onEnded).not.toHaveBeenCalled();
    });

    it("checks once for several 401s at the same time", async () => {
        const fetchMock = vi.fn(async () => new Response(null, { status: 401 }));
        vi.stubGlobal("fetch", fetchMock);
        await Promise.all([
            responseInterceptor(new Response(null, { status: 401 }), req("/api/v1/a")),
            responseInterceptor(new Response(null, { status: 401 }), req("/api/v1/b")),
        ]);
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it("ignores other statuses, auth routes and network trouble", async () => {
        const fetchMock = vi.fn(async () => {
            throw new TypeError("offline");
        });
        vi.stubGlobal("fetch", fetchMock);
        await responseInterceptor(new Response(null, { status: 500 }), req("/api/v1/x"));
        await responseInterceptor(new Response(null, { status: 401 }), req("/api/v1/auth/login"));
        expect(fetchMock).not.toHaveBeenCalled();
        await responseInterceptor(new Response(null, { status: 401 }), req("/api/v1/x"));
        expect(onEnded).not.toHaveBeenCalled();
    });
});
