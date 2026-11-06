import { client } from "@/client/client.gen";
import { DEFAULT_FEATURE_FLAGS, type FeatureFlags, parseFeatureFlags, setRuntimeFeatureFlags } from "@/config/features";

// A failed read is retried before the defaults are used, so a slow start (the
// token or the API base URL not ready yet) doesn't hide an area that is on.
const RETRY_DELAYS_MS = [1000, 3000];

let latestLoad = 0;

async function readFeatureFlags(): Promise<FeatureFlags | null> {
    try {
        const response = await client.get({ url: "/api/v1/features" });
        return response.error === undefined ? parseFeatureFlags(response.data) : null;
    } catch {
        return null;
    }
}

/**
 * Read the signed-in organisation's feature switches (GET /api/v1/features)
 * into the runtime store. If every attempt fails, the defaults in
 * config/features.ts apply. Only the newest call stores its answer, so an
 * older read can't overwrite a newer organisation's switches.
 */
export async function loadFeatureFlags(): Promise<void> {
    const load = ++latestLoad;
    for (let attempt = 0; ; attempt++) {
        const flags = await readFeatureFlags();
        if (load !== latestLoad) return;
        if (flags || attempt >= RETRY_DELAYS_MS.length) {
            setRuntimeFeatureFlags(flags ?? DEFAULT_FEATURE_FLAGS);
            return;
        }
        await new Promise((resolve) => setTimeout(resolve, RETRY_DELAYS_MS[attempt]));
        if (load !== latestLoad) return;
    }
}
