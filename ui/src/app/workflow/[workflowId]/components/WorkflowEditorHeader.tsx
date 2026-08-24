"use client";

import { ReactFlowInstance } from "@xyflow/react";
import { AlertCircle, Clipboard, Copy, Download, Eye, History, LoaderCircle, MoreVertical, Pencil, Phone, Rocket } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { toast } from "sonner";

import {
    duplicateWorkflowEndpointApiV1WorkflowWorkflowIdDuplicatePost,
    publishWorkflowApiV1WorkflowWorkflowIdPublishPost,
} from "@/client/sdk.gen";
import { WorkflowError } from "@/client/types.gen";
import { FlowEdge, FlowNode } from "@/components/flow/types";
import { PageActions } from "@/components/layout/PageActionsSlot";
import { Button } from "@/components/ui/button";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from "@/components/ui/popover";
import { copyTextToClipboard } from "@/lib/clipboard";

interface WorkflowEditorHeaderProps {
    workflowName: string;
    isDirty: boolean;
    workflowValidationErrors: WorkflowError[];
    rfInstance: React.RefObject<ReactFlowInstance<FlowNode, FlowEdge> | null>;
    workflowId: number;
    workflowUuid?: string;
    saveWorkflow: (updateWorkflowDefinition?: boolean) => Promise<void>;
    user: { id: string; email?: string };
    onPhoneCallClick: () => void;
    onHistoryClick: () => void;
    activeVersionLabel?: string;
    isViewingHistoricalVersion: boolean;
    onBackToDraft: () => void;
    hasDraft: boolean;
    onPublished: () => void;
    renameWorkflow: (newName: string) => Promise<void>;
}

/**
 * Chrome for the Conversation section only.
 *
 * The agent's identity, the back-to-the-workspace row and the section nav all
 * belong to the shell now (app-doc/claude-design/Failte AI v2.dc.html keeps
 * them fixed while the centre panel changes), so what is left here is the flow
 * canvas's own state: which version you are on, whether it is saved, and what
 * is wrong with it. The call-to-action buttons ride the app header through
 * <PageActions>, the way every other screen sends its primary action up.
 */
export const WorkflowEditorHeader = ({
    workflowName,
    isDirty,
    workflowValidationErrors,
    rfInstance,
    saveWorkflow,
    onPhoneCallClick,
    onHistoryClick,
    activeVersionLabel,
    isViewingHistoricalVersion,
    onBackToDraft,
    hasDraft,
    onPublished,
    workflowId,
    workflowUuid,
    renameWorkflow,
}: WorkflowEditorHeaderProps) => {
    const router = useRouter();
    const [savingWorkflow, setSavingWorkflow] = useState(false);
    const [duplicating, setDuplicating] = useState(false);
    const [publishing, setPublishing] = useState(false);
    // One discriminated-union state instead of (isEditingName, nameDraft,
    // nameError, isRenaming): they're not independent — error and saving are
    // mutually exclusive, and both are meaningless in the display state. The
    // union makes the bad combinations unrepresentable and structurally
    // prevents the Enter→disable-input→blur→re-fire race.
    type RenameState =
        | { kind: "display" }
        | { kind: "editing"; draft: string; error: string | null }
        | { kind: "saving"; draft: string };
    const [rename, setRename] = useState<RenameState>({ kind: "display" });
    const nameInputRef = useRef<HTMLInputElement>(null);
    const renameButtonRef = useRef<HTMLButtonElement>(null);

    const hasValidationErrors = workflowValidationErrors.length > 0;
    const isCallDisabled = isDirty || hasValidationErrors;

    const handleSave = async () => {
        setSavingWorkflow(true);
        await saveWorkflow();
        setSavingWorkflow(false);
    };

    const handlePublish = async () => {
        if (publishing) return;
        setPublishing(true);
        const promise = publishWorkflowApiV1WorkflowWorkflowIdPublishPost({
            path: { workflow_id: workflowId },
        });
        toast.promise(promise, {
            loading: "Publishing...",
            success: "Workflow published successfully",
            error: "Failed to publish workflow",
        });
        try {
            await promise;
            onPublished();
        } finally {
            setPublishing(false);
        }
    };

    const handleDuplicate = async () => {
        if (duplicating) return;
        setDuplicating(true);
        const promise = duplicateWorkflowEndpointApiV1WorkflowWorkflowIdDuplicatePost({
            path: { workflow_id: workflowId },
        });
        toast.promise(promise, {
            loading: "Duplicating workflow...",
            success: "Workflow duplicated successfully",
            error: "Failed to duplicate workflow",
        });
        try {
            const { data } = await promise;
            if (data?.id) {
                router.push(`/workflow/${data.id}`);
            }
        } finally {
            setDuplicating(false);
        }
    };

    const handleCopyAgentUuid = async () => {
        if (!workflowUuid) {
            toast.error("Agent UUID not available");
            return;
        }
        try {
            await copyTextToClipboard(workflowUuid);
            toast.success("Agent UUID copied");
        } catch {
            toast.error("Failed to copy Agent UUID");
        }
    };

    const handleDownloadWorkflow = () => {
        if (!rfInstance.current) return;

        const workflowDefinition = rfInstance.current.toObject();
        const exportData = {
            name: workflowName,
            workflow_definition: workflowDefinition,
        };

        const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${workflowName}.json`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    };

    const enterEditMode = () => {
        setRename({ kind: "editing", draft: workflowName, error: null });
    };

    const exitEditMode = () => {
        setRename({ kind: "display" });
        // Return focus to the pencil button so keyboard users aren't stranded.
        // Defer to next tick so React commits the input unmount first.
        setTimeout(() => renameButtonRef.current?.focus(), 0);
    };

    const attemptSave = async () => {
        // Only "editing" can initiate a save. This also guards against the
        // blur fired when disabling the input transitions us to "saving".
        if (rename.kind !== "editing") return;
        const trimmed = rename.draft.trim();
        if (trimmed.length === 0) {
            setRename({ ...rename, error: "Name cannot be empty" });
            return;
        }
        if (trimmed === workflowName) {
            // No-op: exit cleanly with no API call.
            exitEditMode();
            return;
        }
        setRename({ kind: "saving", draft: rename.draft });
        try {
            await renameWorkflow(trimmed);
            // Success: store update already propagated workflowName. Exit edit mode.
            exitEditMode();
        } catch {
            // Roll back: keep user's typed value, reopen the input, focus it,
            // surface a sonner toast (matches existing duplicate/publish failure pattern).
            toast.error("Failed to rename workflow");
            setRename({ kind: "editing", draft: trimmed, error: null });
            setTimeout(() => nameInputRef.current?.focus(), 0);
        }
    };

    const handleRenameKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
        if (event.key === "Enter") {
            event.preventDefault();
            void attemptSave();
        } else if (event.key === "Escape") {
            event.preventDefault();
            exitEditMode();
        }
    };

    const handleRenameBlur = () => {
        // Ignore the blur fired when the input is disabled during save.
        if (rename.kind !== "editing") return;
        // On blur with empty/whitespace, revert silently to display mode so the user is never trapped.
        if (rename.draft.trim().length === 0) {
            exitEditMode();
            return;
        }
        void attemptSave();
    };

    return (
        <>
            {/* Primary actions ride the app header, next to the breadcrumb. */}
            <PageActions>
                {!isViewingHistoricalVersion && (
                    <Button
                        variant="outline"
                        className="flex items-center gap-2 border-line bg-transparent text-foreground hover:bg-panel-2"
                        disabled={isCallDisabled}
                        onClick={onPhoneCallClick}
                    >
                        <Phone className="h-4 w-4" />
                        Phone call
                    </Button>
                )}

                {isViewingHistoricalVersion ? (
                    <Button
                        onClick={onBackToDraft}
                        className="bg-primary px-4 text-primary-foreground hover:bg-primary/90"
                    >
                        Back to draft
                    </Button>
                ) : (
                    <>
                        <Button
                            onClick={handleSave}
                            disabled={!isDirty || savingWorkflow}
                            variant="outline"
                            className="border-line bg-transparent px-4 text-foreground hover:bg-panel-2"
                        >
                            {savingWorkflow ? (
                                <>
                                    <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
                                    Saving…
                                </>
                            ) : (
                                "Save"
                            )}
                        </Button>

                        {hasDraft && (
                            <Button
                                onClick={handlePublish}
                                disabled={isDirty || publishing || hasValidationErrors}
                                className="bg-primary px-4 text-primary-foreground hover:bg-primary/90"
                            >
                                {publishing ? (
                                    <>
                                        <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
                                        Publishing…
                                    </>
                                ) : (
                                    <>
                                        <Rocket className="mr-2 h-4 w-4" />
                                        Publish
                                    </>
                                )}
                            </Button>
                        )}
                    </>
                )}

                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button
                            variant="ghost"
                            size="icon"
                            aria-label="More agent actions"
                            className="text-ink-3 hover:bg-panel-2 hover:text-foreground"
                        >
                            <MoreVertical className="h-5 w-5" />
                        </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="border-line bg-panel">
                        <DropdownMenuItem
                            onClick={handleDuplicate}
                            disabled={duplicating}
                            className="cursor-pointer text-foreground hover:bg-panel-2"
                        >
                            {duplicating ? (
                                <LoaderCircle className="mr-2 h-4 w-4 animate-spin" />
                            ) : (
                                <Copy className="mr-2 h-4 w-4" />
                            )}
                            {duplicating ? "Duplicating..." : "Duplicate agent"}
                        </DropdownMenuItem>
                        <DropdownMenuItem
                            onClick={handleDownloadWorkflow}
                            className="cursor-pointer text-foreground hover:bg-panel-2"
                        >
                            <Download className="mr-2 h-4 w-4" />
                            Download agent
                        </DropdownMenuItem>
                        <DropdownMenuItem
                            onClick={handleCopyAgentUuid}
                            disabled={!workflowUuid}
                            className="cursor-pointer text-foreground hover:bg-panel-2"
                        >
                            <Clipboard className="mr-2 h-4 w-4" />
                            Copy agent UUID
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            </PageActions>

            {/* Section toolbar: state of the flow you are looking at. */}
            <div className="flex h-12 flex-none items-center gap-3 overflow-x-auto border-b border-line-soft px-4">
                {rename.kind !== "display" ? (
                    <div className="flex flex-col gap-1">
                        <Input
                            ref={nameInputRef}
                            value={rename.draft}
                            onChange={(e) => {
                                // onChange can't fire while disabled (kind === "saving"),
                                // but the type guard is needed for the discriminated union.
                                if (rename.kind === "editing") {
                                    setRename({ ...rename, draft: e.target.value, error: null });
                                }
                            }}
                            onKeyDown={handleRenameKeyDown}
                            onBlur={handleRenameBlur}
                            disabled={rename.kind === "saving"}
                            autoFocus
                            onFocus={(e) => e.currentTarget.select()}
                            aria-label="Agent name"
                            aria-invalid={rename.kind === "editing" && rename.error !== null}
                            className="h-8 max-w-xs border-line bg-panel-2 text-sm font-medium text-foreground"
                        />
                        {rename.kind === "editing" && rename.error && (
                            <span className="text-xs text-danger" role="alert">{rename.error}</span>
                        )}
                    </div>
                ) : (
                    !isViewingHistoricalVersion && (
                        // The name itself is in the header and the nav panel, so
                        // this is the rename affordance and nothing else.
                        <button
                            ref={renameButtonRef}
                            type="button"
                            onClick={enterEditMode}
                            className="flex flex-none items-center gap-2 rounded-md border border-line px-2.5 py-1.5 text-sm text-ink-2 transition-colors hover:bg-panel-2 hover:text-foreground"
                        >
                            <Pencil className="h-4 w-4" />
                            Rename
                        </button>
                    )
                )}

                <button
                    onClick={onHistoryClick}
                    className="flex flex-none cursor-pointer items-center gap-2 rounded-md border border-line px-3 py-1.5 transition-colors hover:bg-panel-2"
                >
                    <History className="h-4 w-4 text-ink-3" />
                    {activeVersionLabel && !isViewingHistoricalVersion && (
                        <span className="text-sm text-ink-2">{activeVersionLabel}</span>
                    )}
                </button>

                {isViewingHistoricalVersion && (
                    <div className="flex flex-none items-center gap-2 rounded-md border border-sky/30 bg-sky-dim px-3 py-1.5">
                        <Eye className="h-4 w-4 text-sky" />
                        <span className="text-sm text-sky">
                            Viewing {activeVersionLabel} — read only
                        </span>
                    </div>
                )}

                {isDirty && !isViewingHistoricalVersion && (
                    <div className="flex flex-none items-center gap-2 rounded-md border border-amber/30 bg-amber-dim px-3 py-1.5">
                        <div className="h-2 w-2 rounded-full bg-amber" />
                        <span className="text-sm text-amber">Unsaved changes</span>
                    </div>
                )}

                {hasValidationErrors && (
                    <Popover>
                        <PopoverTrigger asChild>
                            <button className="flex flex-none cursor-pointer items-center gap-2 rounded-md border border-danger/30 bg-danger-dim px-3 py-1.5 transition-colors hover:bg-danger/20">
                                <div className="h-2 w-2 animate-pulse rounded-full bg-danger" />
                                <AlertCircle className="h-4 w-4 text-danger" />
                                <span className="text-sm text-danger">
                                    {workflowValidationErrors.length} {workflowValidationErrors.length === 1 ? "error" : "errors"}
                                </span>
                            </button>
                        </PopoverTrigger>
                        <PopoverContent
                            align="start"
                            className="w-80 border-line bg-panel p-0"
                        >
                            <div className="border-b border-line px-4 py-3">
                                <h3 className="text-sm font-medium text-foreground">Validation errors</h3>
                            </div>
                            <div className="max-h-64 overflow-y-auto">
                                {workflowValidationErrors.map((error, index) => (
                                    <div
                                        key={index}
                                        className="border-b border-line-soft px-4 py-3 last:border-b-0"
                                    >
                                        <div className="flex items-start gap-2">
                                            <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0 text-danger" />
                                            <div className="min-w-0 flex-1">
                                                {(error.kind === "node" || error.kind === "edge") && error.id && (
                                                    <p className="mb-1 text-xs text-ink-3">
                                                        {error.kind === "node" ? "Node" : "Edge"}: {error.id}
                                                        {error.field && <span className="text-ink-3"> • {error.field}</span>}
                                                    </p>
                                                )}
                                                <p className="break-words text-sm text-foreground">
                                                    {error.message}
                                                </p>
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </PopoverContent>
                    </Popover>
                )}
            </div>
        </>
    );
};
