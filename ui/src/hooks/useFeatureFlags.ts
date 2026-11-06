import { useSyncExternalStore } from "react";

import {
    DEFAULT_FEATURE_FLAGS,
    type Feature,
    type FeatureFlags,
    getFeatureFlags,
    hasRuntimeFeatureFlags,
    subscribeToFeatureFlags,
} from "@/config/features";

/** The switches the signed-in organisation sees (defaults until read);
 *  re-renders when they are read or change. */
export function useFeatureFlags(): FeatureFlags {
    return useSyncExternalStore(subscribeToFeatureFlags, getFeatureFlags, () => DEFAULT_FEATURE_FLAGS);
}

/** Whether the runtime switches have been read yet. */
export function useFeatureFlagsLoaded(): boolean {
    return useSyncExternalStore(subscribeToFeatureFlags, hasRuntimeFeatureFlags, () => false);
}

export function useFeatureEnabled(feature: Feature): boolean {
    return useFeatureFlags()[feature];
}
