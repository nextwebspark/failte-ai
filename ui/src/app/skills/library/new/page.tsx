"use client";

import { UnsavedChangesProvider } from "@/context/UnsavedChangesContext";

import { SkillsGate } from "../../access";
import { LibrarySkillEditor } from "../../editor/LibrarySkillEditor";

export default function NewLibrarySkillPage() {
    return (
        <SkillsGate>
            <UnsavedChangesProvider>
                <LibrarySkillEditor libraryUuid={null} />
            </UnsavedChangesProvider>
        </SkillsGate>
    );
}
