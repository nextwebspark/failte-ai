"use client";

import { useParams } from "next/navigation";

import { UnsavedChangesProvider } from "@/context/UnsavedChangesContext";

import { SkillsGate } from "../../access";
import { LibrarySkillEditor } from "../../editor/LibrarySkillEditor";

export default function LibrarySkillPage() {
    const { libraryUuid } = useParams<{ libraryUuid: string }>();
    return (
        <SkillsGate>
            <UnsavedChangesProvider>
                <LibrarySkillEditor key={libraryUuid} libraryUuid={libraryUuid} />
            </UnsavedChangesProvider>
        </SkillsGate>
    );
}
