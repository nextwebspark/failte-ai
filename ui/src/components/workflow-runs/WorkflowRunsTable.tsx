"use client";

import { AlertCircle, ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, ExternalLink, PhoneCall, RefreshCw, RotateCw } from "lucide-react";
import Link from "next/link";
import { type ReactNode, useState } from "react";

import { WorkflowRunResponseSchema } from "@/client/types.gen";
import { CallTypeCell } from "@/components/CallTypeCell";
import { FilterBuilder } from "@/components/filters/FilterBuilder";
import { runDetailHref } from "@/components/layout/shellContext";
import { MediaPreviewButton, MediaPreviewDialog } from "@/components/MediaPreviewDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table";
import { useOrganizationTimezone } from "@/hooks/useOrganizationTimezone";
import { formatDateTime } from "@/lib/dateTime";
import { ROW_LINK } from "@/lib/rowLink";
import { ActiveFilter, FilterAttribute } from "@/types/filters";

/** The calm empty / error shape the Calls page uses: round icon, bold line, one sentence, one action. */
function RunsMessage({
    icon,
    title,
    children,
    action,
    danger = false,
    role,
}: {
    icon: ReactNode;
    title: string;
    children?: ReactNode;
    action?: ReactNode;
    danger?: boolean;
    role?: "alert";
}) {
    return (
        <div role={role} className="flex flex-col items-center gap-2 rounded-xl border border-line bg-panel px-6 py-12 text-center">
            <span
                aria-hidden
                className={`grid size-11 place-items-center rounded-full [&_svg]:size-5 ${danger ? "bg-danger-dim text-danger" : "bg-brand-dim text-brand"}`}
            >
                {icon}
            </span>
            <p className="font-semibold text-foreground">{title}</p>
            {children ? <p className="max-w-sm text-sm text-ink-3">{children}</p> : null}
            {action ? <div className="mt-2">{action}</div> : null}
        </div>
    );
}

export interface WorkflowRunsTableProps {
    // Data
    runs: WorkflowRunResponseSchema[];
    loading: boolean;
    error: string | null;

    // Pagination
    currentPage: number;
    totalPages: number;
    totalCount: number;
    onPageChange: (page: number) => void;

    // Filters
    availableAttributes: FilterAttribute[];
    activeFilters: ActiveFilter[];
    onFiltersChange: (filters: ActiveFilter[]) => void;
    onApplyFilters: () => void;
    onClearFilters: () => void;
    isExecutingFilters: boolean;
    hasAppliedFilters?: boolean;

    // Sorting
    sortBy?: string | null;
    sortOrder?: 'asc' | 'desc';
    onSort?: (field: string) => void;

    // Navigation & Actions
    workflowId: number;
    /**
     * This list's own URL (path + query). Opening a run carries it along so the
     * run screen keeps this screen's shell and can return to it unchanged.
     */
    returnTo?: string;

    // Reload
    onReload?: () => void;

    // Optional customization
    title?: string;
    subtitle?: string;
    showFilters?: boolean;
    showAgentVersion?: boolean;
    emptyMessage?: string;
    /** One helpful sentence under the empty title. */
    emptyHint?: string;
    /** One next step under the empty title, e.g. a test-call button. */
    emptyAction?: ReactNode;
}

export function WorkflowRunsTable({
    runs,
    loading,
    error,
    currentPage,
    totalPages,
    totalCount,
    onPageChange,
    availableAttributes,
    activeFilters,
    onFiltersChange,
    onApplyFilters,
    onClearFilters,
    isExecutingFilters,
    hasAppliedFilters = false,
    sortBy,
    sortOrder = 'desc',
    onSort,
    returnTo,
    onReload,
    title = "Run history",
    subtitle,
    showFilters = true,
    showAgentVersion = false,
    emptyMessage = "No runs yet",
    emptyHint,
    emptyAction,
}: WorkflowRunsTableProps) {
    const [selectedRowId, setSelectedRowId] = useState<number | null>(null);
    const organizationTimezone = useOrganizationTimezone();

    // Media preview dialog
    const mediaPreview = MediaPreviewDialog();

    // Same tab: the run screen keeps this list's shell and links back to it.
    // Use the run's own workflow: a campaign with a traffic split mixes runs
    // from several agents in one list.
    const hrefFor = (run: WorkflowRunResponseSchema) => runDetailHref(run.workflow_id, run.id, returnTo);

    return (
        <div className="space-y-6">
            {/* Title and Filters */}
            {showFilters && (
                <div className="mb-6">
                    {/* The shell prints the screen name in the app header, so a
                        caller that already has one there passes title="". */}
                    {title && <h1 className="text-2xl font-bold mb-4">{title}</h1>}
                    <FilterBuilder
                        availableAttributes={availableAttributes}
                        activeFilters={activeFilters}
                        onFiltersChange={onFiltersChange}
                        onApplyFilters={onApplyFilters}
                        onClearFilters={onClearFilters}
                        isExecuting={isExecutingFilters}
                        hasAppliedFilters={hasAppliedFilters}
                    />
                </div>
            )}

            {/* Loading State */}
            {loading ? (
                <div className="space-y-2 rounded-xl border border-line bg-panel p-4" aria-busy="true" aria-label="Loading calls">
                    <Skeleton className="h-5 w-40" />
                    {[0, 1, 2, 3].map((i) => (
                        <Skeleton key={i} className="h-11 w-full" />
                    ))}
                </div>
            ) : error ? (
                <RunsMessage
                    role="alert"
                    danger
                    icon={<AlertCircle />}
                    title="We couldn't load these calls"
                    action={
                        onReload ? (
                            <Button variant="outline" onClick={onReload} className="min-h-10">
                                <RotateCw className="size-4" aria-hidden />
                                Try again
                            </Button>
                        ) : undefined
                    }
                >
                    Please check your connection and try again.
                </RunsMessage>
            ) : runs.length === 0 ? (
                <RunsMessage icon={<PhoneCall />} title={emptyMessage} action={emptyAction}>
                    {emptyHint}
                </RunsMessage>
            ) : (
                <Card>
                    <CardHeader>
                        <div className="flex items-center justify-between">
                            <div>
                                <CardTitle>Calls</CardTitle>
                                <CardDescription>
                                    {subtitle || `Showing ${runs.length} of ${totalCount} ${totalCount === 1 ? "call" : "calls"}`}
                                </CardDescription>
                            </div>
                            {onReload && (
                                <Button
                                    variant="outline"
                                    size="icon"
                                    onClick={onReload}
                                    disabled={loading}
                                    title="Reload"
                                    aria-label="Reload calls"
                                >
                                    <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} aria-hidden />
                                </Button>
                            )}
                        </div>
                    </CardHeader>
                    <CardContent>
                        <div className="bg-card border border-border rounded-lg overflow-hidden shadow-sm">
                            <Table>
                                <TableHeader>
                                    <TableRow className="bg-muted/50">
                                        <TableHead className="font-semibold">ID</TableHead>
                                        {showAgentVersion && <TableHead>Agent / version</TableHead>}
                                        <TableHead className="font-semibold">Status</TableHead>
                                        <TableHead className="font-semibold">Created</TableHead>
                                        <TableHead className="font-semibold">Call type</TableHead>
                                        <TableHead
                                            className="font-semibold"
                                            aria-sort={sortBy === 'duration' ? (sortOrder === 'asc' ? 'ascending' : 'descending') : undefined}
                                        >
                                            {onSort ? (
                                                <button
                                                    type="button"
                                                    className="-mx-1 flex items-center gap-1 rounded px-1 outline-none hover:bg-muted/50 focus-visible:ring-[3px] focus-visible:ring-ring/40"
                                                    onClick={() => onSort('duration')}
                                                >
                                                    Duration
                                                    {sortBy === 'duration' ? (
                                                        sortOrder === 'asc' ? <ArrowUp className="h-4 w-4" aria-hidden /> : <ArrowDown className="h-4 w-4" aria-hidden />
                                                    ) : (
                                                        <ArrowUpDown className="h-4 w-4 text-muted-foreground" aria-hidden />
                                                    )}
                                                    <span className="sr-only">, sort</span>
                                                </button>
                                            ) : (
                                                'Duration'
                                            )}
                                        </TableHead>
                                        <TableHead className="font-semibold">Outcome</TableHead>
                                        <TableHead className="font-semibold">Actions</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {runs.map((run) => (
                                        <TableRow
                                            key={run.id}
                                            // The call number is a real link stretched over the row, so a
                                            // click anywhere opens the call, and keyboard focus, middle-click
                                            // and "open in new tab" all work. The actions sit above it.
                                            className={`relative hover:bg-muted/50 focus-within:bg-muted/50 ${selectedRowId === run.id ? "bg-primary/20 ring-1 ring-primary/50" : ""}`}
                                        >
                                            <TableCell className="font-mono text-sm">
                                                <Link
                                                    href={hrefFor(run)}
                                                    aria-label={`Open call #${run.id}`}
                                                    className={ROW_LINK}
                                                >
                                                    #{run.id}
                                                </Link>
                                            </TableCell>
                                            {showAgentVersion && <TableCell><div>{run.workflow_name ?? `Agent #${run.workflow_id}`}</div><div className="text-xs text-muted-foreground">{run.version_number != null ? `Version ${run.version_number}` : run.definition_id != null ? `Definition #${run.definition_id}` : 'Unversioned'}</div></TableCell>}
                                            <TableCell>
                                                <Badge variant={run.is_completed ? "default" : "secondary"}>
                                                    {run.is_completed ? "Completed" : "In progress"}
                                                </Badge>
                                            </TableCell>
                                            <TableCell className="text-sm">
                                                {formatDateTime(run.created_at, organizationTimezone)}
                                            </TableCell>
                                            <TableCell>
                                                <CallTypeCell mode={run.mode} callType={run.call_type} />
                                            </TableCell>
                                            <TableCell className="text-sm">
                                                {typeof run.cost_info?.call_duration_seconds === 'number'
                                                    ? `${run.cost_info.call_duration_seconds.toFixed(1)}s`
                                                    : "-"}
                                            </TableCell>
                                            <TableCell>
                                                {run.gathered_context?.mapped_call_disposition ? (
                                                    <Badge variant="default">
                                                        {run.gathered_context.mapped_call_disposition as string}
                                                    </Badge>
                                                ) : (
                                                    <span className="text-sm text-muted-foreground">-</span>
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                <div className="relative z-10 flex space-x-2">
                                                    <MediaPreviewButton
                                                        recordingUrl={run.recording_url}
                                                        transcriptUrl={run.transcript_url}
                                                        runId={run.id}
                                                        onOpenPreview={mediaPreview.openPreview}
                                                        onSelect={setSelectedRowId}
                                                    />
                                                    <Button asChild variant="outline" size="icon">
                                                        <a
                                                            href={hrefFor(run)}
                                                            target="_blank"
                                                            rel="noopener noreferrer"
                                                            title="Open call in a new tab"
                                                            aria-label={`Open call #${run.id} in a new tab`}
                                                        >
                                                            <ExternalLink className="h-4 w-4" aria-hidden />
                                                        </a>
                                                    </Button>
                                                </div>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </div>

                        {/* Pagination */}
                        {totalPages > 1 && (
                            <div className="flex items-center justify-between mt-6">
                                <p className="text-sm text-muted-foreground">
                                    Page {currentPage} of {totalPages}
                                </p>
                                <div className="flex gap-2">
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => onPageChange(currentPage - 1)}
                                        disabled={currentPage === 1}
                                    >
                                        <ChevronLeft className="h-4 w-4" aria-hidden />
                                        Previous
                                    </Button>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => onPageChange(currentPage + 1)}
                                        disabled={currentPage === totalPages}
                                    >
                                        Next
                                        <ChevronRight className="h-4 w-4" aria-hidden />
                                    </Button>
                                </div>
                            </div>
                        )}
                    </CardContent>
                </Card>
            )}

            {/* Media Preview Dialog */}
            {mediaPreview.dialog}
        </div>
    );
}
