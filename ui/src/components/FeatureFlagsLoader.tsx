"use client";

import { useEffect } from "react";

import { setRuntimeFeatureFlags } from "@/config/features";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { useAuth } from "@/lib/auth";
import { loadFeatureFlags } from "@/lib/featureFlags";

/** Reads the feature switches once signed in, and again when the selected
 *  organisation changes (an organisation can have its own overrides). */
export function FeatureFlagsLoader() {
    const { loading, isAuthenticated } = useAuth();
    const { orgContext } = useOrgConfig();
    const organizationId = orgContext?.organization_id ?? null;

    useEffect(() => {
        if (loading) return;
        if (!isAuthenticated) {
            // Signed out: forget the last organisation's switches.
            setRuntimeFeatureFlags(null);
            return;
        }
        void loadFeatureFlags();
    }, [loading, isAuthenticated, organizationId]);

    return null;
}
