"use client";

import { NoAccess } from "@/components/auth/NoAccess";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { UnsavedChangesProvider } from "@/context/UnsavedChangesContext";

import { SkillsGate } from "../access";
import { WorkspaceSkillEditor } from "../editor/WorkspaceSkillEditor";

export default function NewSkillPage() {
    const { can, role } = useOrgConfig();
    return (
        <SkillsGate>
            {can("agents:write") ? (
                <UnsavedChangesProvider>
                    <WorkspaceSkillEditor skillUuid={null} />
                </UnsavedChangesProvider>
            ) : (
                <NoAccess role={role} />
            )}
        </SkillsGate>
    );
}
