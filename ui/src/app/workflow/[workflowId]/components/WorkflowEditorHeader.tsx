"use client";

import { ReactFlowInstance } from "@xyflow/react";
import { AlertCircle, Clipboard, Copy, Download, Eye, History, LoaderCircle, MoreHorizontal, Pencil, Phone, Rocket } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { toast } from "sonner";

import {
    duplicateWorkflowEndpointApiV1WorkflowWorkflowIdDuplicatePost,
    publishWorkflowApiV1WorkflowWorkflowIdPublishPost,
} from "@/client/sdk.gen";
import { WorkflowError } from "@/client/types.gen";
import { FlowEdge, FlowNode } from "@/components/flow/types";
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
import { StatusPill } from "@/components/ui/status-pill";
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
 * The Conversation screen's one toolbar (app-doc/claude-design/v3-audit,
 * Conversation.dc.html): the agent's name as its rename control, the version
 * you are on, unsaved and error pills, then Phone call / Save / Publish / more.
 * The agent's identity and section nav stay in the shell's agent panel.
 */
type StepLookup = Pick<ReactFlowInstance<FlowNode, FlowEdge>, "getNode" | "getEdge">;

/**
 * Where a validation error is, by step name: the canvas no longer shows ids,
 * so "Step: 7" or "Connection: 3-5" would point at nothing the user can see.
 */
export function describeErrorTarget(error: WorkflowError & { id: string }, flow: StepLookup | null): string {
    const stepName = (id: string) => flow?.getNode(id)?.data?.name || id;
    if (error.kind === "node") return `Step: ${stepName(error.id)}`;
    const edge = flow?.getEdge(error.id);
    return edge ? `Connection: ${stepName(edge.source)} → ${stepName(edge.target)}` : `Connection: ${error.id}`;
}

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
    // Why the saved draft can't be called or published, in the order the user should act on it.
    const draftBlocker = isDirty
        ? "Save first"
        : hasValidationErrors
            ? "Fix the errors first"
            : null;
    const publishBlocker = draftBlocker ?? (hasDraft ? null : "Nothing new to publish");
    // Disabled buttons drop pointer events by default, which would hide their title.
    const explainWhenDisabled = "disabled:pointer-events-auto disabled:cursor-not-allowed";

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
            success: "Agent published",
            error: "Failed to publish agent",
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
            loading: "Duplicating agent…",
            success: "Agent duplicated",
            error: "Failed to duplicate agent",
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
            toast.error("Failed to rename agent");
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
        // One toolbar for the Conversation screen: what you are editing, its
        // state, and what you can do with it. It no longer portals into the
        // app header, so the header keeps only the breadcrumb.
        <div
            role="group"
            aria-label="Agent"
            className="flex min-h-[52px] flex-none flex-wrap items-center gap-x-2 gap-y-1.5 border-b border-line-soft px-3.5 py-2 md:flex-nowrap"
        >
            {/* What you are editing: shrinks (the name truncates) so the
                actions keep one row; on a phone the actions take a second. */}
            <div className="flex min-w-0 basis-full items-center gap-2 md:flex-1 md:basis-auto">
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
                            className="h-8 w-64 max-w-full border-line bg-panel-2 text-sm font-semibold text-foreground"
                        />
                        {rename.kind === "editing" && rename.error && (
                            <span className="text-xs text-danger" role="alert">{rename.error}</span>
                        )}
                    </div>
                ) : isViewingHistoricalVersion ? (
                    <span className="min-w-0 max-w-[280px] truncate px-1 text-sm font-semibold text-foreground">
                        {workflowName}
                    </span>
                ) : (
                    // The name is the rename control.
                    <button
                        ref={renameButtonRef}
                        type="button"
                        onClick={enterEditMode}
                        aria-label={`Rename agent: ${workflowName}`}
                        title="Rename"
                        className="group flex h-8 min-w-0 max-w-[280px] items-center gap-2 rounded-md border border-transparent px-2 text-sm font-semibold text-foreground transition-colors hover:border-line hover:bg-panel-2 focus-visible:outline-2 focus-visible:outline-ring"
                    >
                        <span className="truncate">{workflowName}</span>
                        <Pencil className="h-3.5 w-3.5 shrink-0 text-ink-3 group-hover:text-ink-2" aria-hidden />
                    </button>
                )}

                <button
                    type="button"
                    onClick={onHistoryClick}
                    aria-label={activeVersionLabel ? `Version history, ${activeVersionLabel}` : "Version history"}
                    className="flex h-7 flex-none items-center gap-1.5 whitespace-nowrap rounded-sm border border-line bg-panel px-2.5 font-mono text-[11.5px] text-ink-2 transition-colors hover:bg-panel-2 hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
                >
                    <History className="h-3 w-3" aria-hidden />
                    {activeVersionLabel ?? "History"}
                </button>

                {isViewingHistoricalVersion && (
                    <StatusPill tone="info" className="flex-none gap-1.5">
                        <Eye className="h-3 w-3" aria-hidden />
                        Read only
                    </StatusPill>
                )}

                {isDirty && !isViewingHistoricalVersion && (
                    <StatusPill tone="warn" dot className="flex-none" role="status">
                        Unsaved
                    </StatusPill>
                )}

                {hasValidationErrors && (
                    <Popover>
                        <PopoverTrigger asChild>
                            <button
                                type="button"
                                className="flex-none rounded-sm focus-visible:outline-2 focus-visible:outline-ring"
                            >
                                <StatusPill tone="bad" className="gap-1.5 hover:bg-danger/20">
                                    <AlertCircle className="h-3 w-3" aria-hidden />
                                    {workflowValidationErrors.length} {workflowValidationErrors.length === 1 ? "error" : "errors"}
                                </StatusPill>
                            </button>
                        </PopoverTrigger>
                        <PopoverContent align="start" className="w-80 border-line bg-panel p-0">
                            <div className="border-b border-line px-4 py-3">
                                <h3 className="text-sm font-medium text-foreground">Fix before calling or publishing</h3>
                            </div>
                            <div className="max-h-64 overflow-y-auto">
                                {workflowValidationErrors.map((error, index) => (
                                    <div key={index} className="border-b border-line-soft px-4 py-3 last:border-b-0">
                                        <div className="flex items-start gap-2">
                                            <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0 text-danger" />
                                            <div className="min-w-0 flex-1">
                                                {(error.kind === "node" || error.kind === "edge") && error.id && (
                                                    <p className="mb-1 text-xs text-ink-3">
                                                        {describeErrorTarget({ ...error, id: error.id }, rfInstance.current)}
                                                        {error.field && <span className="text-ink-3"> • {error.field}</span>}
                                                    </p>
                                                )}
                                                <p className="break-words text-sm text-foreground">{error.message}</p>
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </PopoverContent>
                    </Popover>
                )}
            </div>

            {/* Toolbar-size controls (32px, 12.5px), per the design system. */}
            <div className="ml-auto flex flex-none items-center gap-2 [&_[data-slot=button]]:text-[12.5px] [&_[data-slot=button]_svg]:size-3.5">
                {isViewingHistoricalVersion ? (
                    <Button size="sm" onClick={onBackToDraft}>
                        Back to draft
                    </Button>
                ) : (
                    <>
                        <Button
                            variant="outline"
                            size="sm"
                            disabled={draftBlocker !== null}
                            onClick={onPhoneCallClick}
                            aria-label="Phone call"
                            title={draftBlocker ?? undefined}
                            className={explainWhenDisabled}
                        >
                            <Phone />
                            <span className="hidden sm:inline">Phone call</span>
                        </Button>
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={handleSave}
                            disabled={!isDirty || savingWorkflow}
                        >
                            {savingWorkflow && <LoaderCircle className="animate-spin" />}
                            {savingWorkflow ? "Saving…" : "Save"}
                        </Button>
                        <Button
                            size="sm"
                            onClick={handlePublish}
                            disabled={publishing || publishBlocker !== null}
                            title={publishBlocker ?? undefined}
                            className={explainWhenDisabled}
                        >
                            {publishing ? <LoaderCircle className="animate-spin" /> : <Rocket />}
                            {publishing ? "Publishing…" : "Publish"}
                        </Button>
                    </>
                )}

                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button
                            variant="outline"
                            size="icon"
                            aria-label="More agent actions"
                            className="size-8 text-ink-3 hover:text-foreground"
                        >
                            <MoreHorizontal />
                        </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-52">
                        <DropdownMenuItem onClick={handleDuplicate} disabled={duplicating}>
                            {duplicating ? <LoaderCircle className="animate-spin" /> : <Copy />}
                            {duplicating ? "Duplicating…" : "Duplicate agent"}
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={handleDownloadWorkflow}>
                            <Download />
                            Download agent
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={handleCopyAgentUuid} disabled={!workflowUuid}>
                            <Clipboard />
                            Copy agent UUID
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
        </div>
    );
};
