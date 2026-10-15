import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSyncPolling } from "./useSyncPolling";

const OPTIONS = { intervalMs: 1000, limitMs: 10_000 };

beforeEach(() => {
    vi.useFakeTimers();
});

afterEach(() => {
    vi.useRealTimers();
    Object.defineProperty(document, "hidden", { configurable: true, value: false });
});

async function advance(ms: number) {
    await act(async () => {
        await vi.advanceTimersByTimeAsync(ms);
    });
}

describe("useSyncPolling", () => {
    it("polls one request at a time while active", async () => {
        let release: () => void = () => {};
        const reload = vi.fn(() => new Promise<void>((resolve) => (release = resolve)));
        renderHook(() => useSyncPolling(true, reload, OPTIONS));

        await advance(1000);
        expect(reload).toHaveBeenCalledTimes(1);
        // The next poll waits for the slow one to finish.
        await advance(5000);
        expect(reload).toHaveBeenCalledTimes(1);
        release();
        await advance(1000);
        expect(reload).toHaveBeenCalledTimes(2);
    });

    it("stops when the sync finishes and on unmount", async () => {
        const reload = vi.fn(async () => {});
        const { rerender, unmount } = renderHook(({ active }) => useSyncPolling(active, reload, OPTIONS), {
            initialProps: { active: true },
        });
        await advance(2000);
        expect(reload).toHaveBeenCalledTimes(2);
        rerender({ active: false });
        await advance(5000);
        expect(reload).toHaveBeenCalledTimes(2);

        rerender({ active: true });
        await advance(1000);
        expect(reload).toHaveBeenCalledTimes(3);
        unmount();
        await advance(5000);
        expect(reload).toHaveBeenCalledTimes(3);
    });

    it("pauses while the tab is hidden", async () => {
        const reload = vi.fn(async () => {});
        Object.defineProperty(document, "hidden", { configurable: true, value: true });
        renderHook(() => useSyncPolling(true, reload, OPTIONS));
        await advance(3000);
        expect(reload).not.toHaveBeenCalled();
        Object.defineProperty(document, "hidden", { configurable: true, value: false });
        await advance(1000);
        expect(reload).toHaveBeenCalledTimes(1);
    });

    it("gives up after the limit", async () => {
        const reload = vi.fn(async () => {});
        const { result } = renderHook(() => useSyncPolling(true, reload, OPTIONS));
        expect(result.current).toBe(false);
        await advance(12_000);
        expect(result.current).toBe(true);
        const calls = reload.mock.calls.length;
        await advance(5000);
        expect(reload).toHaveBeenCalledTimes(calls);
    });
});
