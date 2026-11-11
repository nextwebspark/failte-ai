// Product areas that are built but not offered to everyone yet. Off hides the
// area in the app: its nav row and pages (middleware and the app shell send
// them to Overview), and the controls that lead to it elsewhere. The API,
// stored data and running calls are not affected.
//
// Platform admins switch them at runtime (Platform admin > Features), for
// everyone or per organisation. The values below are the defaults, used until
// the app has read the switches and whenever the API can't be reached. Keep
// them in step with api/services/platform_admin/features.py.

export const FEATURES = {
    /** Outbound calls in bulk to a contact list (/campaigns). */
    campaigns: false,
    /** Playbooks agents load mid-call (/skills, and the pickers on agent steps). */
    skills: false,
} as const;

export type Feature = keyof typeof FEATURES;
export type FeatureFlags = Record<Feature, boolean>;

const FEATURE_KEYS = Object.keys(FEATURES) as Feature[];

/** The build-time defaults as a plain record. */
export const DEFAULT_FEATURE_FLAGS: FeatureFlags = { ...FEATURES };

/**
 * Feature flags from an API response (`{ features: { campaigns: true } }`).
 * Unknown keys and non-boolean values are ignored; missing keys keep their
 * default. Returns null when the body is not a feature list at all.
 */
export function parseFeatureFlags(body: unknown): FeatureFlags | null {
    const features = (body as { features?: unknown } | null)?.features;
    if (!features || typeof features !== "object") {
        return null;
    }
    const flags: FeatureFlags = { ...DEFAULT_FEATURE_FLAGS };
    for (const key of FEATURE_KEYS) {
        const value = (features as Record<string, unknown>)[key];
        if (typeof value === "boolean") {
            flags[key] = value;
        }
    }
    return flags;
}

// -- runtime values (the signed-in organisation's switches) -----------------

let runtimeFlags: FeatureFlags | null = null;
const listeners = new Set<() => void>();

/** Store the switches read from the API (null: back to the defaults). */
export function setRuntimeFeatureFlags(flags: FeatureFlags | null): void {
    runtimeFlags = flags;
    listeners.forEach((listener) => listener());
}

/** Whether the runtime switches have been read (false: defaults in use). */
export function hasRuntimeFeatureFlags(): boolean {
    return runtimeFlags !== null;
}

export function getFeatureFlags(): FeatureFlags {
    return runtimeFlags ?? DEFAULT_FEATURE_FLAGS;
}

/** Called whenever the runtime switches change (hooks/useFeatureFlags.ts). */
export function subscribeToFeatureFlags(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
        listeners.delete(listener);
    };
}

/** Outside React (e.g. in a callback): the current value. */
export function isFeatureEnabled(feature: Feature): boolean {
    return getFeatureFlags()[feature];
}

/** Where each area's pages live. */
const AREA_ROUTES: Record<Feature, string> = {
    campaigns: "/campaigns",
    skills: "/skills",
};

/** The feature whose pages contain this path, or null. */
export function featureForRoute(pathname: string): Feature | null {
    return (
        FEATURE_KEYS.find((feature) => {
            const root = AREA_ROUTES[feature];
            return pathname === root || pathname.startsWith(`${root}/`);
        }) ?? null
    );
}

/** A page of an area that is switched off (the area's root or anything under it). */
export function isSwitchedOffRoute(pathname: string, flags: FeatureFlags = getFeatureFlags()): boolean {
    const feature = featureForRoute(pathname);
    return feature !== null && !flags[feature];
}
