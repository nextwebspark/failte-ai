import type { WorkflowListResponse } from '@/client/types.gen';
import { formatDate } from '@/lib/dateTime';

/**
 * Pure helpers behind the Voice agents landing: the status an agent shows, the
 * search / filter / sort applied to the list, the stat strip, and the "last
 * call" wording. Kept free of React so they can be unit tested.
 */

export type AgentStatus = 'published' | 'draft' | 'archived';
export type AgentStatusFilter = 'all' | 'published' | 'draft';
export type AgentSort = 'last_call' | 'name' | 'newest';

export const AGENT_STATUS_LABEL: Record<AgentStatus, string> = {
    published: 'Published',
    draft: 'Unpublished',
    archived: 'Archived',
};

export function agentStatus(agent: WorkflowListResponse): AgentStatus {
    if (agent.status === 'archived') return 'archived';
    return agent.has_draft ? 'draft' : 'published';
}

/** Calls in the last 7 days; falls back to zero when the API didn't send them. */
export function weeklyRuns(agent: WorkflowListResponse): number {
    return (agent.runs_7d ?? []).reduce((sum, n) => sum + n, 0);
}

export function filterAgents(
    agents: WorkflowListResponse[],
    query: string,
    status: AgentStatusFilter,
): WorkflowListResponse[] {
    const needle = query.trim().toLowerCase();
    return agents.filter((agent) => {
        if (status !== 'all' && agentStatus(agent) !== status) return false;
        if (!needle) return true;
        return (
            agent.name.toLowerCase().includes(needle) ||
            String(agent.id) === needle
        );
    });
}

function time(value?: string | null): number {
    return value ? new Date(value).getTime() : 0;
}

export function sortAgents(
    agents: WorkflowListResponse[],
    sort: AgentSort,
): WorkflowListResponse[] {
    const sorted = [...agents];
    if (sort === 'name') {
        sorted.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));
    } else if (sort === 'newest') {
        sorted.sort((a, b) => time(b.created_at) - time(a.created_at));
    } else {
        // Most recent call first; agents that never ran fall to the bottom,
        // newest first among themselves.
        sorted.sort(
            (a, b) =>
                time(b.last_run_at) - time(a.last_run_at) ||
                time(b.created_at) - time(a.created_at),
        );
    }
    return sorted;
}

export interface AgentStats {
    total: number;
    published: number;
    callsToday: number;
    callsYesterday: number;
    callsWeek: number;
    lastCallAt: string | null;
}

/** Totals for the stat strip, over active agents only. */
export function agentStats(agents: WorkflowListResponse[]): AgentStats {
    const stats: AgentStats = {
        total: agents.length,
        published: 0,
        callsToday: 0,
        callsYesterday: 0,
        callsWeek: 0,
        lastCallAt: null,
    };
    for (const agent of agents) {
        if (agentStatus(agent) === 'published') stats.published += 1;
        const days = agent.runs_7d ?? [];
        stats.callsToday += days[days.length - 1] ?? 0;
        stats.callsYesterday += days[days.length - 2] ?? 0;
        stats.callsWeek += weeklyRuns(agent);
        if (agent.last_run_at && time(agent.last_run_at) > time(stats.lastCallAt)) {
            stats.lastCallAt = agent.last_run_at;
        }
    }
    return stats;
}

/** Whole-percent change from `before` to `after`, or null when there's no base. */
export function percentChange(before: number, after: number): number | null {
    if (before === 0) return null;
    return Math.round(((after - before) / before) * 100);
}

function dayKey(value: Date, timezone: string): string {
    return value.toLocaleDateString('en-CA', { timeZone: timezone });
}

/**
 * "Just now", "12 min ago", "Today, 09:12", "Yesterday", or a date. Days are
 * judged in the organization's timezone.
 */
export function formatLastCall(
    value: string | null | undefined,
    timezone: string,
    now: Date = new Date(),
): string {
    if (!value) return 'Never';
    const at = new Date(value);
    const minutes = Math.floor((now.getTime() - at.getTime()) / 60_000);
    if (minutes < 1) return 'Just now';
    if (minutes < 60) return `${minutes} min ago`;

    if (dayKey(at, timezone) === dayKey(now, timezone)) {
        const clock = at.toLocaleTimeString('en-GB', {
            timeZone: timezone,
            hour: '2-digit',
            minute: '2-digit',
        });
        return `Today, ${clock}`;
    }
    const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
    if (dayKey(at, timezone) === dayKey(yesterday, timezone)) return 'Yesterday';
    return formatDate(at, timezone);
}

/**
 * SVG polyline points for a sparkline of `values` in a `width` x `height` box,
 * leaving `pad` px for the stroke. A flat series sits on the baseline.
 */
export function sparklinePoints(
    values: number[],
    width = 64,
    height = 20,
    pad = 2,
): string {
    if (values.length === 0) return '';
    const max = Math.max(...values);
    const step = values.length > 1 ? (width - pad * 2) / (values.length - 1) : 0;
    return values
        .map((value, i) => {
            const x = pad + i * step;
            const y = max === 0 ? height - pad : height - pad - (value / max) * (height - pad * 2);
            return `${Number(x.toFixed(1))},${Number(y.toFixed(1))}`;
        })
        .join(' ');
}
