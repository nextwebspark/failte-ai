'use client';

import {
    Archive,
    Check,
    Folder as FolderIcon,
    FolderInput,
    Inbox,
    MoreHorizontal,
    Pencil,
    RotateCcw,
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState, useTransition } from 'react';
import { toast } from 'sonner';

import {
    moveWorkflowToFolderApiV1WorkflowWorkflowIdFolderPut,
    updateWorkflowStatusApiV1WorkflowWorkflowIdStatusPut,
} from '@/client/sdk.gen';
import type { FolderResponse, WorkflowListResponse } from '@/client/types.gen';
import { Button } from '@/components/ui/button';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { StatusPill, statusTone } from '@/components/ui/status-pill';
import { useOrganizationTimezone } from '@/hooks/useOrganizationTimezone';
import {
    AGENT_STATUS_LABEL,
    agentStatus,
    formatLastCall,
    sparklinePoints,
    weeklyRuns,
} from '@/lib/agentList';
import { formatDate } from '@/lib/dateTime';
import { cn } from '@/lib/utils';

interface WorkflowTableProps {
    workflows: WorkflowListResponse[];
    showArchived: boolean;
    /**
     * When provided, each row's menu gets a "Move to folder" submenu listing
     * these folders. Omit it (e.g. for the archived list) to hide the control.
     */
    folders?: FolderResponse[];
}

// Agent · Status · Calls (7 days) · Last call · menu. Narrow screens keep the
// agent and the menu; the status drops under the name.
const ROW_GRID =
    'grid grid-cols-[minmax(0,1fr)_40px] items-center gap-3 px-4 md:grid-cols-[minmax(0,1fr)_130px_150px_130px_40px]';

function Sparkline({ values }: { values: number[] }) {
    const active = values.some((v) => v > 0);
    return (
        <svg
            width="64"
            height="20"
            viewBox="0 0 64 20"
            aria-hidden
            className={cn('shrink-0', active ? 'text-brand' : 'text-line')}
        >
            <polyline
                points={sparklinePoints(values)}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinejoin="round"
                strokeLinecap="round"
            />
        </svg>
    );
}

/**
 * The Voice agents list: one row per agent. The row opens the agent; the
 * secondary actions (move, archive, restore) live in its ⋯ menu.
 */
export function WorkflowTable({ workflows, showArchived, folders }: WorkflowTableProps) {
    const router = useRouter();
    const timezone = useOrganizationTimezone();
    const [isPending, startTransition] = useTransition();
    const [busyWorkflowId, setBusyWorkflowId] = useState<number | null>(null);

    const handleOpen = (id: number) => {
        router.push(`/workflow/${id}`);
    };

    const handleArchiveToggle = async (id: number, currentStatus: string) => {
        const newStatus = currentStatus === 'active' ? 'archived' : 'active';
        const action = currentStatus === 'active' ? 'archive' : 'restore';

        setBusyWorkflowId(id);
        try {
            const response = await updateWorkflowStatusApiV1WorkflowWorkflowIdStatusPut({
                path: { workflow_id: id },
                body: { status: newStatus },
            });
            if (response.error) {
                throw new Error(`Failed to ${action} agent`);
            }
            toast.success(`Agent ${action}d`);
            startTransition(() => {
                router.refresh();
            });
        } catch (error) {
            console.error(`Error trying to ${action} workflow:`, error);
            toast.error(`Failed to ${action} agent`);
        } finally {
            setBusyWorkflowId(null);
        }
    };

    const handleMove = async (id: number, folderId: number | null) => {
        setBusyWorkflowId(id);
        try {
            const response = await moveWorkflowToFolderApiV1WorkflowWorkflowIdFolderPut({
                path: { workflow_id: id },
                body: { folder_id: folderId },
            });
            if (response.error) {
                throw new Error('Failed to move agent');
            }
            toast.success(folderId === null ? 'Moved to Uncategorized' : 'Agent moved');
            startTransition(() => {
                router.refresh();
            });
        } catch (error) {
            console.error('Error moving workflow:', error);
            toast.error('Failed to move agent');
        } finally {
            setBusyWorkflowId(null);
        }
    };

    return (
        <div className="overflow-hidden rounded-lg border border-line bg-card">
            <div
                className={cn(
                    ROW_GRID,
                    'hidden h-9 border-b border-line-soft bg-panel-2 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-ink-3 md:grid',
                )}
                aria-hidden
            >
                <span>Agent</span>
                <span>Status</span>
                <span>Calls · 7 days</span>
                <span>Last call</span>
                <span />
            </div>
            <ul className="divide-y divide-line-soft">
                {workflows.map((workflow) => {
                    const status = agentStatus(workflow);
                    const busy = busyWorkflowId === workflow.id;
                    const folderId = workflow.folder_id ?? null;
                    const pill = (
                        <StatusPill tone={statusTone(status)}>
                            {AGENT_STATUS_LABEL[status]}
                        </StatusPill>
                    );

                    return (
                        <li
                            key={workflow.id}
                            role="link"
                            tabIndex={0}
                            aria-label={`Open ${workflow.name}`}
                            className={cn(
                                ROW_GRID,
                                'min-h-[60px] cursor-pointer py-2.5 transition-colors hover:bg-panel-2 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring',
                                showArchived && 'text-ink-2',
                            )}
                            onClick={() => handleOpen(workflow.id)}
                            onKeyDown={(event) => {
                                if (event.target !== event.currentTarget) return;
                                if (event.key === 'Enter' || event.key === ' ') {
                                    event.preventDefault();
                                    handleOpen(workflow.id);
                                }
                            }}
                        >
                            <div className="flex min-w-0 items-center gap-3">
                                <span
                                    aria-hidden
                                    className={cn(
                                        'flex size-8 shrink-0 items-center justify-center rounded-full border border-line bg-panel-2 text-[13px] font-semibold text-ink-2',
                                        showArchived && 'opacity-60',
                                    )}
                                >
                                    {workflow.name.trim().charAt(0).toUpperCase() || '?'}
                                </span>
                                <div className="min-w-0">
                                    <div
                                        className={cn(
                                            'truncate text-[14px] font-medium',
                                            showArchived ? 'text-ink-2' : 'text-ink',
                                        )}
                                    >
                                        {workflow.name}
                                    </div>
                                    <div className="mt-0.5 flex items-center gap-2 text-[12px] text-ink-3">
                                        <span className="font-mono">#{workflow.id}</span>
                                        {/* Narrow screens trade the date for the status. */}
                                        <span className="hidden md:inline" aria-hidden>·</span>
                                        <span className="hidden truncate md:inline" suppressHydrationWarning>
                                            Created {formatDate(workflow.created_at, timezone)}
                                        </span>
                                        <span className="md:hidden">{pill}</span>
                                    </div>
                                </div>
                            </div>

                            <div className="hidden md:block">{pill}</div>

                            <div className="hidden items-center gap-2.5 md:flex">
                                <span className="min-w-[2.5ch] text-right font-mono text-[13px] font-medium text-ink">
                                    {weeklyRuns(workflow)}
                                </span>
                                <Sparkline values={workflow.runs_7d ?? []} />
                            </div>

                            <div
                                className="hidden text-[13px] text-ink-2 md:block"
                                title={`${workflow.total_runs} calls in total`}
                                suppressHydrationWarning
                            >
                                {formatLastCall(workflow.last_run_at, timezone)}
                            </div>

                            <div
                                className="flex justify-end"
                                onClick={(event) => event.stopPropagation()}
                                onKeyDown={(event) => event.stopPropagation()}
                            >
                                <DropdownMenu>
                                    <DropdownMenuTrigger asChild>
                                        <Button
                                            variant="ghost"
                                            size="icon"
                                            className="size-8 text-ink-3 hover:text-ink"
                                            disabled={busy || isPending}
                                            aria-label={`Actions for ${workflow.name}`}
                                        >
                                            {busy ? (
                                                <span className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                                            ) : (
                                                <MoreHorizontal size={16} />
                                            )}
                                        </Button>
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent align="end" className="w-52">
                                        <DropdownMenuItem onClick={() => handleOpen(workflow.id)}>
                                            <Pencil size={14} />
                                            Open
                                        </DropdownMenuItem>
                                        {folders && (
                                            <DropdownMenuSub>
                                                <DropdownMenuSubTrigger className="gap-2">
                                                    <FolderInput size={14} />
                                                    Move to folder
                                                </DropdownMenuSubTrigger>
                                                <DropdownMenuSubContent className="w-52">
                                                    <DropdownMenuItem
                                                        disabled={folderId === null}
                                                        onClick={() => handleMove(workflow.id, null)}
                                                    >
                                                        <Inbox size={14} />
                                                        Uncategorized
                                                        {folderId === null && (
                                                            <Check size={14} className="ml-auto" />
                                                        )}
                                                    </DropdownMenuItem>
                                                    {folders.map((folder) => (
                                                        <DropdownMenuItem
                                                            key={folder.id}
                                                            disabled={folder.id === folderId}
                                                            onClick={() => handleMove(workflow.id, folder.id)}
                                                        >
                                                            <FolderIcon size={14} />
                                                            <span className="truncate">{folder.name}</span>
                                                            {folder.id === folderId && (
                                                                <Check size={14} className="ml-auto shrink-0" />
                                                            )}
                                                        </DropdownMenuItem>
                                                    ))}
                                                </DropdownMenuSubContent>
                                            </DropdownMenuSub>
                                        )}
                                        <DropdownMenuSeparator />
                                        <DropdownMenuItem
                                            onClick={() => handleArchiveToggle(workflow.id, workflow.status)}
                                        >
                                            {showArchived ? (
                                                <>
                                                    <RotateCcw size={14} />
                                                    Restore
                                                </>
                                            ) : (
                                                <>
                                                    <Archive size={14} />
                                                    Archive
                                                </>
                                            )}
                                        </DropdownMenuItem>
                                    </DropdownMenuContent>
                                </DropdownMenu>
                            </div>
                        </li>
                    );
                })}
            </ul>
        </div>
    );
}
