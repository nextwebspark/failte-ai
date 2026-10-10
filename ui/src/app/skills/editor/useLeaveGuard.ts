"use client";

import { useEffect } from "react";

import { useUnsavedChanges } from "@/context/UnsavedChangesContext";

/**
 * Warns before leaving with unsaved edits: in-app links and back/forward go
 * through the UnsavedChangesProvider dialog, closing or reloading the tab
 * through the browser's own prompt.
 */
export function useLeaveGuard(sectionId: string, dirty: boolean) {
    useUnsavedChanges(sectionId, dirty);
    useEffect(() => {
        if (!dirty) return;
        const onBeforeUnload = (event: BeforeUnloadEvent) => {
            event.preventDefault();
            // Older browsers only prompt when returnValue is set.
            event.returnValue = "";
        };
        window.addEventListener("beforeunload", onBeforeUnload);
        return () => window.removeEventListener("beforeunload", onBeforeUnload);
    }, [dirty]);
}
