"use client";

import type { ReactNode } from "react";

import { NoAccess } from "@/components/auth/NoAccess";
import { useOrgConfig } from "@/context/OrgConfigContext";

/**
 * Skills are agent configuration: every role can read them (`agents:read`),
 * developers and admins can change them (`agents:write`).
 */
export function SkillsGate({ children }: { children: ReactNode }) {
    const { can, role, loading } = useOrgConfig();
    if (!can("agents:read")) {
        // The role is still loading: render nothing rather than flash "no access".
        if (role === null && loading) return null;
        return <NoAccess role={role} />;
    }
    return <>{children}</>;
}

export function useCanEditSkills(): boolean {
    const { can } = useOrgConfig();
    return can("agents:write");
}
