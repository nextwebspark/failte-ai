"use client";

import { Loader2 } from "lucide-react";
import {
    createContext,
    type ReactNode,
    useCallback,
    useContext,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
} from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import type { WorkflowConfigurations } from "@/types/workflow-configurations";

/**
 * One save bar for the whole Advanced settings page (v3 audit, step 6).
 *
 * Each section keeps its own form state and registers what it would save:
 * - `configurations` sections (General, Voicemail) return a patch; every
 *   dirty patch is merged into ONE configurations save, so two sections can
 *   never overwrite each other with a stale copy of the other's fields;
 * - `own` sections (Variables, Dictionary) save through their own endpoint.
 *
 * The own saves run first: they send the agent name as it was when the page
 * rendered, so the configurations save (which carries a rename) goes last.
 */

export interface ConfigurationsPatch {
    configurations: Partial<WorkflowConfigurations>;
    /** Present when the section edits the agent's name. */
    workflowName?: string;
}

interface SectionEntry {
    label: string;
    dirty: boolean;
    /** Why this section can't be saved yet, or null. */
    blocker: string | null;
    patch?: () => ConfigurationsPatch;
    save?: () => Promise<void>;
    /** Runs after a successful save, e.g. to normalise what the form shows. */
    afterSave?: () => void;
}

interface SaveBarContextValue {
    report: (id: string, entry: SectionEntry) => void;
    remove: (id: string) => void;
}

const SaveBarContext = createContext<SaveBarContextValue | null>(null);

/** Registers a section with the page's save bar. Call it on every render. */
export function useSettingsSection(id: string, entry: SectionEntry) {
    const context = useContext(SaveBarContext);
    const { dirty, blocker, label } = entry;
    const hasPatch = entry.patch !== undefined;
    const hasSave = entry.save !== undefined;
    // The bar calls through this ref, so it always gets the latest form state
    // without the section re-registering on every keystroke.
    const latest = useRef(entry);
    latest.current = entry;
    useLayoutEffect(() => {
        context?.report(id, {
            label,
            dirty,
            blocker,
            patch: hasPatch ? () => latest.current.patch!() : undefined,
            save: hasSave ? () => latest.current.save!() : undefined,
            afterSave: () => latest.current.afterSave?.(),
        });
    }, [context, id, label, dirty, blocker, hasPatch, hasSave]);
    useLayoutEffect(() => () => context?.remove(id), [context, id]);
}

interface SettingsSaveProviderProps {
    children: ReactNode;
    workflowName: string;
    workflowConfigurations: WorkflowConfigurations;
    saveWorkflowConfigurations: (configurations: WorkflowConfigurations, workflowName: string) => Promise<void>;
    /** Throws away every unsaved edit (the page remounts its sections). */
    onDiscard: () => void;
    /** Shown after a successful save. */
    savedMessage: string;
}

interface Registered extends SectionEntry {
    id: string;
    order: number;
}

export function SettingsSaveProvider({
    children,
    workflowName,
    workflowConfigurations,
    saveWorkflowConfigurations,
    onDiscard,
    savedMessage,
}: SettingsSaveProviderProps) {
    const [sections, setSections] = useState<Record<string, Registered>>({});
    const [saving, setSaving] = useState(false);
    const nextOrder = useRef(0);

    const report = useCallback((id: string, entry: SectionEntry) => {
        setSections((current) => ({
            ...current,
            [id]: { ...entry, id, order: current[id]?.order ?? nextOrder.current++ },
        }));
    }, []);
    const remove = useCallback((id: string) => {
        setSections((current) => {
            if (!(id in current)) return current;
            const next = { ...current };
            delete next[id];
            return next;
        });
    }, []);
    const contextValue = useMemo(() => ({ report, remove }), [report, remove]);

    const dirty = Object.values(sections)
        .filter((section) => section.dirty)
        .sort((a, b) => a.order - b.order);
    const blocked = dirty.find((section) => section.blocker !== null);

    const save = async () => {
        if (saving || dirty.length === 0 || blocked) return;
        setSaving(true);
        try {
            for (const section of dirty.filter((s) => s.save)) {
                await section.save!();
            }
            const patches = dirty.filter((s) => s.patch).map((s) => s.patch!());
            if (patches.length > 0) {
                const configurations = patches.reduce<WorkflowConfigurations>(
                    (merged, { configurations: part }) => ({ ...merged, ...part }),
                    workflowConfigurations,
                );
                const name = patches.find((p) => p.workflowName !== undefined)?.workflowName ?? workflowName;
                await saveWorkflowConfigurations(configurations, name);
            }
            dirty.forEach((section) => section.afterSave?.());
            toast.success(savedMessage);
        } catch (error) {
            toast.error(error instanceof Error && error.message ? error.message : "Couldn’t save your changes");
        } finally {
            setSaving(false);
        }
    };

    return (
        <SaveBarContext.Provider value={contextValue}>
            {children}
            {dirty.length > 0 && (
                // Sticky to the bottom of the scrolling content panel.
                <div className="pointer-events-none sticky bottom-4 z-20 flex justify-center px-4">
                    <div
                        role="status"
                        aria-live="polite"
                        className="pointer-events-auto flex max-w-full flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-line bg-panel py-2 pr-2 pl-4 shadow-[var(--panel-shadow)]"
                    >
                        <span className="flex min-w-0 items-center gap-2 text-[13px] text-ink-2">
                            <span aria-hidden className="size-2 shrink-0 rounded-full bg-amber" />
                            <span className="min-w-0">
                                <strong className="font-semibold text-foreground">
                                    {dirty.length === 1 ? "1 section" : `${dirty.length} sections`}
                                </strong>{" "}
                                not saved · {dirty.map((s) => s.label).join(", ")}
                            </span>
                        </span>
                        {blocked && (
                            <span className="text-[12.5px] text-danger">
                                {blocked.label}: {blocked.blocker}
                            </span>
                        )}
                        <div className="ml-auto flex gap-2">
                            <Button variant="outline" size="sm" onClick={onDiscard} disabled={saving}>
                                Discard
                            </Button>
                            <Button size="sm" onClick={save} disabled={saving || !!blocked}>
                                {saving && <Loader2 className="animate-spin" />}
                                {saving ? "Saving…" : "Save changes"}
                            </Button>
                        </div>
                    </div>
                </div>
            )}
        </SaveBarContext.Provider>
    );
}
