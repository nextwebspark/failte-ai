import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useVoicePreview } from "@/hooks/useVoicePreview";

vi.mock("@/lib/auth", () => ({ useAuth: () => ({ getAccessToken: async () => "token" }) }));
vi.mock("@/lib/apiClient", async (importOriginal) => ({
    ...(await importOriginal<typeof import("@/lib/apiClient")>()),
    resolveBrowserBackendUrl: () => "http://api",
}));

const created: FakeAudio[] = [];
class FakeAudio {
    onended: (() => void) | null = null;
    onerror: (() => void) | null = null;
    play = vi.fn().mockResolvedValue(undefined);
    pause = vi.fn();
    constructor(public src: string) {
        created.push(this);
    }
}
const revoke = vi.fn();
let blobCount = 0;

beforeEach(() => {
    created.length = 0;
    revoke.mockClear();
    vi.stubGlobal("Audio", FakeAudio);
    vi.stubGlobal("URL", { ...URL, createObjectURL: () => `blob:${++blobCount}`, revokeObjectURL: revoke });
});
afterEach(() => vi.unstubAllGlobals());

function deferredFetch() {
    let resolve: (value: unknown) => void = () => {};
    const promise = new Promise((r) => (resolve = r));
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(promise));
    return () => resolve({ ok: true, blob: async () => new Blob(["x"]) });
}

describe("useVoicePreview", () => {
    it("plays absolute URLs directly and toggles off", async () => {
        const { result } = renderHook(() => useVoicePreview());

        await act(() => result.current.toggle("a", "https://cdn/a.mp3"));
        expect(created[0].src).toBe("https://cdn/a.mp3");
        expect(result.current.playingId).toBe("a");

        await act(() => result.current.toggle("a", "https://cdn/a.mp3"));
        expect(created[0].pause).toHaveBeenCalled();
        expect(result.current.playingId).toBeNull();
    });

    it("discards a sample that arrives after the user moved on", async () => {
        const arrive = deferredFetch();
        const { result } = renderHook(() => useVoicePreview());

        let pending: Promise<void> = Promise.resolve();
        act(() => {
            pending = result.current.toggle("a", "/preview?voice_id=a");
        });
        act(() => result.current.stop());
        await act(async () => {
            arrive();
            await pending;
        });

        expect(created).toHaveLength(0);
        expect(revoke).toHaveBeenCalledOnce();
    });

    it("revokes the blob when playback stops and on unmount", async () => {
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(["x"]) }));
        const { result, unmount } = renderHook(() => useVoicePreview());

        await act(() => result.current.toggle("a", "/preview?voice_id=a"));
        expect(created[0].src).toMatch(/^blob:/);
        act(() => created[0].onended?.());
        expect(revoke).toHaveBeenCalledOnce();

        await act(() => result.current.toggle("b", "/preview?voice_id=b"));
        unmount();
        expect(created[1].pause).toHaveBeenCalled();
        expect(revoke).toHaveBeenCalledTimes(2);
    });
});
