"use client";

import { useParams } from "next/navigation";

import { UnsavedChangesProvider } from "@/context/UnsavedChangesContext";

import { SkillsGate } from "../access";
import { WorkspaceSkillEditor } from "../editor/WorkspaceSkillEditor";

export default function SkillDetailPage() {
    const { skillUuid } = useParams<{ skillUuid: string }>();
    return (
        <SkillsGate>
            <UnsavedChangesProvider>
                <WorkspaceSkillEditor key={skillUuid} skillUuid={skillUuid} />
            </UnsavedChangesProvider>
        </SkillsGate>
    );
}
