import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/client/client.gen", () => ({ client: { get: mocks.get } }));

import { getFeatureFlags, hasRuntimeFeatureFlags, setRuntimeFeatureFlags } from "@/config/features";

import { loadFeatureFlags } from "./featureFlags";

describe("loadFeatureFlags", () => {
    beforeEach(() => {
        vi.useFakeTimers();
        mocks.get.mockReset();
    });
    afterEach(() => {
        vi.useRealTimers();
        setRuntimeFeatureFlags(null);
    });

    it("stores the organisation's switches", async () => {
        mocks.get.mockResolvedValue({ data: { features: { campaigns: true, skills: false } } });
        await loadFeatureFlags();
        expect(getFeatureFlags()).toEqual({ campaigns: true, skills: false });
    });

    it("retries a failed read before falling back to the defaults", async () => {
        mocks.get
            .mockResolvedValueOnce({ error: { detail: "Unauthorized" } })
            .mockResolvedValueOnce({ data: { features: { skills: true } } });
        const done = loadFeatureFlags();
        expect(hasRuntimeFeatureFlags()).toBe(false);
        await vi.runAllTimersAsync();
        await done;
        expect(getFeatureFlags()).toEqual({ campaigns: false, skills: true });
    });

    it("uses the defaults when every attempt fails", async () => {
        mocks.get.mockRejectedValue(new Error("offline"));
        const done = loadFeatureFlags();
        await vi.runAllTimersAsync();
        await done;
        expect(mocks.get).toHaveBeenCalledTimes(3);
        expect(hasRuntimeFeatureFlags()).toBe(true);
        expect(getFeatureFlags()).toEqual({ campaigns: false, skills: false });
    });
});
