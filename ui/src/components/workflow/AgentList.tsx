'use client';

import { Search, X } from 'lucide-react';
import { type ReactNode, useEffect, useMemo, useState } from 'react';

import type { FolderResponse, WorkflowListResponse } from '@/client/types.gen';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import { AgentsEmptyState } from '@/components/workflow/AgentsEmptyState';
import { AgentSetupChecklist } from '@/components/workflow/AgentSetupChecklist';
import { AgentFolderView } from '@/components/workflow/folders/AgentFolderView';
import { FolderSection } from '@/components/workflow/folders/FolderSection';
import { WorkflowTable } from '@/components/workflow/WorkflowTable';
import {
    type AgentSort,
    agentStats,
    type AgentStatusFilter,
    DRAFT_EDITS_LABEL,
    filterAgents,
    formatTalkTime,
    percentChange,
    setupProgress,
    sortAgents,
} from '@/lib/agentList';
import { cn } from '@/lib/utils';

interface AgentListProps {
    activeWorkflows: WorkflowListResponse[];
    archivedWorkflows: WorkflowListResponse[];
    folders: FolderResponse[];
}

const SORT_LABEL: Record<AgentSort, string> = {
    last_call: 'Last call',
    name: 'Name',
    newest: 'Newest',
};

const SETUP_HIDDEN_KEY = 'lightmove.agents.setupHidden';

function Stat({ label, children }: { label: string; children: ReactNode }) {
    return (
        <div className="flex flex-col gap-1 rounded-lg border border-line bg-card px-4 py-3.5">
            <span className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-ink-3">
                {label}
            </span>
            <span className="font-display text-[24px] font-semibold leading-tight tracking-[-0.02em] text-ink">
                {children}
            </span>
        </div>
    );
}

function StatNote({ children, className }: { children: ReactNode; className?: string }) {
    return (
        <span className={cn('ml-1.5 font-sans text-[12.5px] font-medium tracking-normal text-ink-3', className)}>
            {children}
        </span>
    );
}

/**
 * The Voice agents landing: a stat strip, then search / status / sort, then the
 * agents grouped by folder. While a search or filter is on, the folders give way
 * to one flat list of matches so nothing hides inside a collapsed folder.
 */
export function AgentList({ activeWorkflows, archivedWorkflows, folders }: AgentListProps) {
    const [query, setQuery] = useState('');
    const [status, setStatus] = useState<AgentStatusFilter>('all');
    const [sort, setSort] = useState<AgentSort>('last_call');

    const stats = useMemo(() => agentStats(activeWorkflows), [activeWorkflows]);
    const setup = useMemo(() => setupProgress(activeWorkflows), [activeWorkflows]);
    // Hiding the checklist is a per-browser preference; read it after mount so
    // the server render and the first client render agree.
    const [setupHidden, setSetupHidden] = useState(false);
    useEffect(() => {
        try {
            setSetupHidden(localStorage.getItem(SETUP_HIDDEN_KEY) === '1');
        } catch {
            // Storage blocked: the checklist just stays visible.
        }
    }, []);
    const hideSetup = () => {
        setSetupHidden(true);
        try {
            localStorage.setItem(SETUP_HIDDEN_KEY, '1');
        } catch {
            // Hidden for this visit only.
        }
    };
    const showSetup = !setupHidden && setup.agent !== null && !(setup.tested && setup.connected);
    // Until a call has happened the stats are all zero, so the checklist stands in for them.
    const showStats = setup.tested || !showSetup;

    const filtering = query.trim() !== '' || status !== 'all';
    const showToolbar = activeWorkflows.length + archivedWorkflows.length > 1 || filtering;
    const sortedActive = useMemo(() => sortAgents(activeWorkflows, sort), [activeWorkflows, sort]);
    const matches = useMemo(
        () => filterAgents(sortedActive, query, status),
        [sortedActive, query, status],
    );
    // Archived agents have their own section; the draft filter hides it, since
    // an archived agent's draft doesn't matter.
    const archived = useMemo(
        () => (status === 'all' ? sortAgents(filterAgents(archivedWorkflows, query, 'all'), sort) : []),
        [archivedWorkflows, query, status, sort],
    );

    const clearFilters = () => {
        setQuery('');
        setStatus('all');
    };

    if (activeWorkflows.length === 0 && folders.length === 0) {
        return (
            <>
                <AgentsEmptyState />
                {archivedWorkflows.length > 0 && (
                    <div className="mt-8">
                        <FolderSection
                            kind="archived"
                            workflows={sortAgents(archivedWorkflows, 'newest')}
                        />
                    </div>
                )}
            </>
        );
    }

    const todayChange = percentChange(stats.callsYesterday, stats.callsToday);
    const filters: { value: AgentStatusFilter; label: string; count: number }[] = [
        { value: 'all', label: 'All', count: stats.total },
        { value: 'draft', label: DRAFT_EDITS_LABEL, count: stats.withDraft },
    ];

    return (
        <div className="space-y-5">
            {showSetup && setup.agent && (
                <AgentSetupChecklist
                    agent={setup.agent}
                    tested={setup.tested}
                    connected={setup.connected}
                    onHide={hideSetup}
                />
            )}
            {showStats && (
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                    <Stat label="Agents">
                        {stats.total}
                        <StatNote>
                            {stats.withDraft > 0 ? `${stats.withDraft} with draft edits` : 'all published'}
                        </StatNote>
                    </Stat>
                    <Stat label="Calls · 24 h">
                        {stats.callsToday.toLocaleString()}
                        {todayChange !== null && (
                            <StatNote className={todayChange >= 0 ? 'text-ok' : 'text-danger'}>
                                {todayChange >= 0 ? '▲' : '▼'} {Math.abs(todayChange)}%
                            </StatNote>
                        )}
                    </Stat>
                    <Stat label="Talk time · 24 h">{formatTalkTime(stats.talkSeconds)}</Stat>
                    <Stat label="Live now">
                        <span className="inline-flex items-center gap-2">
                            {stats.liveNow > 0 && (
                                <span aria-hidden className="size-2 animate-pulse rounded-full bg-live" />
                            )}
                            {stats.liveNow}
                        </span>
                    </Stat>
                </div>
            )}

            {/* Search, filter and sort only help once there is more than one agent. */}
            {showToolbar && (
                <div className="flex flex-wrap items-center gap-2.5">
                    <div className="relative min-w-[200px] flex-1 sm:max-w-[360px]">
                        <Search
                            size={14}
                            aria-hidden
                            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3"
                        />
                        <Input
                            value={query}
                            onChange={(event) => setQuery(event.target.value)}
                            onKeyDown={(event) => {
                                if (event.key === 'Escape') setQuery('');
                            }}
                            placeholder="Search agents"
                            aria-label="Search agents"
                            className="bg-panel-2 pl-8 pr-8"
                        />
                        {query && (
                            <button
                                type="button"
                                onClick={() => setQuery('')}
                                aria-label="Clear search"
                                className="absolute right-1.5 top-1/2 flex size-6 -translate-y-1/2 items-center justify-center rounded-sm text-ink-3 hover:bg-panel hover:text-ink focus-visible:outline-2 focus-visible:outline-ring"
                            >
                                <X size={14} />
                            </button>
                        )}
                    </div>
                    <div
                        role="group"
                        aria-label="Filter by status"
                        className="inline-flex h-9 items-center rounded-md border border-line bg-panel-2 p-0.5"
                    >
                        {filters.map((filter) => (
                            <button
                                key={filter.value}
                                type="button"
                                aria-pressed={status === filter.value}
                                onClick={() => setStatus(filter.value)}
                                className={cn(
                                    'inline-flex h-full items-center gap-1.5 rounded-sm px-3 text-[13px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-ring',
                                    status === filter.value
                                        ? 'bg-card text-ink shadow-xs'
                                        : 'text-ink-3 hover:text-ink',
                                )}
                            >
                                {filter.label}
                                <span className="font-mono text-[11px] text-ink-3">{filter.count}</span>
                            </button>
                        ))}
                    </div>
                    <Select value={sort} onValueChange={(value) => setSort(value as AgentSort)}>
                        <SelectTrigger className="ml-auto w-[160px]" aria-label="Sort agents">
                            <span className="text-ink-3">Sort:</span>
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent align="end">
                            {(Object.keys(SORT_LABEL) as AgentSort[]).map((value) => (
                                <SelectItem key={value} value={value}>
                                    {SORT_LABEL[value]}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
            )}

            {filtering &&
                (matches.length > 0 ? (
                    <div className="space-y-2">
                        <p className="text-[12.5px] text-ink-3" aria-live="polite">
                            {matches.length} {matches.length === 1 ? 'agent' : 'agents'}
                        </p>
                        <WorkflowTable
                            workflows={matches}
                            showArchived={false}
                            folders={folders.length > 0 ? folders : undefined}
                        />
                    </div>
                ) : (
                    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-line bg-panel-2 p-8 text-center text-[13.5px] text-ink-2">
                        {archived.length > 0
                            ? `No active agents match. ${archived.length} archived ${archived.length === 1 ? 'agent matches' : 'agents match'} below.`
                            : query.trim()
                              ? `No agents match “${query.trim()}”.`
                              : 'No agents have draft edits.'}
                        <Button variant="outline" size="sm" onClick={clearFilters}>
                            <X size={14} />
                            Clear filters
                        </Button>
                    </div>
                ))}

            {/* Stays mounted while filtering so folders keep their open state. */}
            <div hidden={filtering}>
                <AgentFolderView workflows={sortedActive} folders={folders} />
            </div>

            {archived.length > 0 && (
                // While searching, archived matches open so none of them hide.
                <FolderSection
                    key={filtering ? 'archived-matches' : 'archived'}
                    kind="archived"
                    workflows={archived}
                    defaultOpen={filtering}
                />
            )}
        </div>
    );
}
