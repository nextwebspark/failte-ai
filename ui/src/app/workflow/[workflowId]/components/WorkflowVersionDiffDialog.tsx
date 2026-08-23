"use client";

import { ChevronsLeft, ChevronsRight } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { WorkflowVersionResponse } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

import {
    buildSideBySideDiffRows,
    type DiffCell,
    serializeWorkflowVersionJson,
} from "../utils/workflowVersionDiff";

interface WorkflowVersionDiffDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    previousVersion: WorkflowVersionResponse;
    selectedVersion: WorkflowVersionResponse;
}

const statusLabel: Record<string, string> = {
    draft: "Draft",
    published: "Published",
    archived: "Archived",
};

const versionLabel = (version: WorkflowVersionResponse): string => {
    return `v${version.version_number}`;
};

const isChangedRow = (row: ReturnType<typeof buildSideBySideDiffRows>[number]): boolean => (
    row.left?.kind === "removed" || row.right?.kind === "added"
);

interface ChangeHunk {
    start: number;
    end: number;
}

const getChangeHunks = (
    rows: ReturnType<typeof buildSideBySideDiffRows>,
): ChangeHunk[] => {
    const hunks: ChangeHunk[] = [];
    let hunkStart: number | null = null;

    rows.forEach((row, index) => {
        if (isChangedRow(row) && hunkStart === null) {
            hunkStart = index;
        }
        else if (!isChangedRow(row) && hunkStart !== null) {
            hunks.push({ start: hunkStart, end: index });
            hunkStart = null;
        }
    });

    if (hunkStart !== null) {
        hunks.push({ start: hunkStart, end: rows.length });
    }

    return hunks;
};

const DiffCellView = ({ cell }: { cell: DiffCell | null }) => (
    <div
        className={cn(
            "h-full min-w-0 border-b border-line-soft px-4 py-1 font-mono text-xs leading-5",
            cell?.kind === "removed" && "bg-danger-dim text-danger",
            cell?.kind === "added" && "bg-ok-dim text-ok",
            cell?.kind === "unchanged" && "bg-panel text-ink-2",
            !cell && "bg-panel-2 text-ink-3",
        )}
    >
        <code className="block min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
            {cell?.segments
                ? cell.segments.map((segment, index) => (
                    <span
                        key={`${index}-${segment.kind}`}
                        className={cn(
                            "box-decoration-clone",
                            segment.kind === "unchanged" && "bg-panel text-ink-2",
                            segment.kind === "removed" && "bg-danger/30 text-foreground",
                            segment.kind === "added" && "bg-ok/30 text-foreground",
                        )}
                    >
                        {segment.text}
                    </span>
                ))
                : (cell?.text ?? " ")}
        </code>
    </div>
);

export const WorkflowVersionDiffDialog = ({
    open,
    onOpenChange,
    previousVersion,
    selectedVersion,
}: WorkflowVersionDiffDialogProps) => {
    const rows = useMemo(() => {
        const previousJson = serializeWorkflowVersionJson(previousVersion);
        const selectedJson = serializeWorkflowVersionJson(selectedVersion);
        return buildSideBySideDiffRows(previousJson, selectedJson);
    }, [previousVersion, selectedVersion]);
    const changeHunks = useMemo(() => getChangeHunks(rows), [rows]);
    const changeHunkElements = useRef<Array<HTMLDivElement | null>>([]);
    const [activeChangeIndex, setActiveChangeIndex] = useState(-1);
    const hasChanges = changeHunks.length > 0;

    useEffect(() => {
        setActiveChangeIndex(-1);
    }, [previousVersion.id, selectedVersion.id]);

    const changeHunkIndexByRow = useMemo(() => new Map(
        changeHunks.map((hunk, hunkIndex) => [hunk.start, hunkIndex]),
    ), [changeHunks]);

    const scrollToChange = useCallback((changeIndex: number) => {
        setActiveChangeIndex(changeIndex);
        changeHunkElements.current[changeIndex]?.scrollIntoView({
            behavior: "smooth",
            block: "center",
        });
    }, []);

    const handlePreviousChange = useCallback(() => {
        if (!hasChanges) return;

        const previousChangeIndex = activeChangeIndex <= 0
            ? changeHunks.length - 1
            : activeChangeIndex - 1;
        scrollToChange(previousChangeIndex);
    }, [activeChangeIndex, changeHunks.length, hasChanges, scrollToChange]);

    const handleNextChange = useCallback(() => {
        if (!hasChanges) return;

        scrollToChange((activeChangeIndex + 1) % changeHunks.length);
    }, [activeChangeIndex, changeHunks.length, hasChanges, scrollToChange]);

    const activeHunk = activeChangeIndex >= 0
        ? changeHunks[activeChangeIndex]
        : null;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="h-[calc(100vh-2rem)] max-h-[900px] w-[calc(100vw-2rem)] max-w-[1280px] grid-rows-[auto_auto_minmax(0,1fr)] gap-0 overflow-hidden border-line bg-panel p-0 sm:max-w-[1280px]">
                <DialogHeader className="border-b border-line px-5 py-4 pr-14">
                    <div className="flex items-center justify-between gap-4">
                        <DialogTitle className="text-base text-foreground">
                            Changes {versionLabel(previousVersion)} → {versionLabel(selectedVersion)}
                        </DialogTitle>
                        {hasChanges && (
                            <div className="flex shrink-0 items-center gap-2">
                                <span
                                    aria-live="polite"
                                    className="min-w-14 text-right text-xs tabular-nums text-ink-3"
                                >
                                    {activeChangeIndex >= 0
                                        ? `${activeChangeIndex + 1} / ${changeHunks.length}`
                                        : `${changeHunks.length} ${changeHunks.length === 1 ? "change" : "changes"}`}
                                </span>
                                <div className="flex items-center gap-1">
                                    <Button
                                        type="button"
                                        variant="outline"
                                        size="icon"
                                        aria-label="Go to previous change"
                                        onClick={handlePreviousChange}
                                        className="h-7 w-7 border-line bg-transparent text-ink-3 hover:bg-panel-2 hover:text-foreground"
                                    >
                                        <ChevronsLeft className="h-3.5 w-3.5" />
                                    </Button>
                                    <Button
                                        type="button"
                                        variant="outline"
                                        size="icon"
                                        aria-label="Go to next change"
                                        onClick={handleNextChange}
                                        className="h-7 w-7 border-line bg-transparent text-ink-3 hover:bg-panel-2 hover:text-foreground"
                                    >
                                        <ChevronsRight className="h-3.5 w-3.5" />
                                    </Button>
                                </div>
                            </div>
                        )}
                    </div>
                    <DialogDescription className="sr-only">
                        Differences between workflow versions {versionLabel(previousVersion)} and {versionLabel(selectedVersion)}.
                    </DialogDescription>
                </DialogHeader>

                <div className="grid grid-cols-2 border-b border-line bg-panel-2 text-sm">
                    <div className="flex items-center gap-2 border-r border-line px-4 py-2">
                        <span className="font-medium text-foreground">
                            {versionLabel(previousVersion)}
                        </span>
                        <span className="text-xs text-ink-3">
                            {statusLabel[previousVersion.status] ?? previousVersion.status}
                        </span>
                    </div>
                    <div className="flex items-center gap-2 px-4 py-2">
                        <span className="font-medium text-foreground">
                            {versionLabel(selectedVersion)}
                        </span>
                        <span className="text-xs text-ink-3">
                            {statusLabel[selectedVersion.status] ?? selectedVersion.status}
                        </span>
                    </div>
                </div>

                <div className="min-h-0 overflow-auto bg-panel">
                    {hasChanges ? (
                        <div className="grid min-w-0 grid-cols-2 items-stretch">
                            {rows.map((row, index) => {
                                const hunkIndex = changeHunkIndexByRow.get(index);
                                const isActiveHunkRow = activeHunk !== null &&
                                    index >= activeHunk.start && index < activeHunk.end;

                                return (
                                    <div
                                        key={`${index}-${row.left?.lineNumber ?? "empty"}-${row.right?.lineNumber ?? "empty"}`}
                                        ref={hunkIndex === undefined ? undefined : (element) => {
                                            changeHunkElements.current[hunkIndex] = element;
                                        }}
                                        className={cn(
                                            "col-span-2 grid min-w-0 grid-cols-2 items-stretch",
                                            isActiveHunkRow && "border-l-2 border-l-sky",
                                        )}
                                    >
                                        <div className="min-w-0 border-r border-line">
                                            <DiffCellView cell={row.left} />
                                        </div>
                                        <div className="min-w-0">
                                            <DiffCellView cell={row.right} />
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    ) : (
                        <p className="py-12 text-center text-sm text-ink-3">No changes</p>
                    )}
                </div>
            </DialogContent>
        </Dialog>
    );
};
