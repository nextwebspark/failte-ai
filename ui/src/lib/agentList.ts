import type { WorkflowListResponse } from '@/client/types.gen';
import { formatDate } from '@/lib/dateTime';

/**
 * Pure helpers behind the Voice agents landing: the status an agent shows, the
 * search / filter / sort applied to the list, the stat strip, and the "last
 * call" wording. Kept free of React so they can be unit tested.
 */

/**
 * Every agent is created with a published version, and saving in the editor
 * only adds a draft next to it, so an active agent is always live. A draft is
 * shown as a second chip, never in place of "Published".
 */
export type AgentStatus = 'published' | 'archived';
/** `draft` narrows the list to agents with saved edits that aren't published. */
export type AgentStatusFilter = 'all' | 'draft';
export type AgentSort = 'last_call' | 'name' | 'newest';

export const AGENT_STATUS_LABEL: Record<AgentStatus, string> = {
    published: 'Published',
    archived: 'Archived',
};

export const DRAFT_EDITS_LABEL = 'Draft edits';

export function agentStatus(agent: WorkflowListResponse): AgentStatus {
    return agent.status === 'archived' ? 'archived' : 'published';
}

export function hasDraftEdits(agent: WorkflowListResponse): boolean {
    return agent.status !== 'archived' && Boolean(agent.has_draft);
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
    // Rows show ids as "#123", so "#123", "123" and "12" all find agent 123.
    const idNeedle = /^#?\d+$/.test(needle) ? needle.replace(/^#/, '') : null;
    return agents.filter((agent) => {
        if (status === 'draft' && !hasDraftEdits(agent)) return false;
        if (!needle) return true;
        return (
            agent.name.toLowerCase().includes(needle) ||
            (idNeedle !== null && String(agent.id).startsWith(idNeedle))
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
    withDraft: number;
    callsToday: number;
    callsYesterday: number;
    /** Seconds of call time in the last 24 hours. */
    talkSeconds: number;
    /** Calls connected right now. */
    liveNow: number;
}

/** Totals for the stat strip, over active agents only. */
export function agentStats(agents: WorkflowListResponse[]): AgentStats {
    const stats: AgentStats = {
        total: agents.length,
        withDraft: 0,
        callsToday: 0,
        callsYesterday: 0,
        talkSeconds: 0,
        liveNow: 0,
    };
    for (const agent of agents) {
        if (hasDraftEdits(agent)) stats.withDraft += 1;
        const days = agent.runs_7d ?? [];
        stats.callsToday += days[days.length - 1] ?? 0;
        stats.callsYesterday += days[days.length - 2] ?? 0;
        stats.talkSeconds += agent.talk_seconds_24h ?? 0;
        stats.liveNow += agent.live_calls ?? 0;
    }
    return stats;
}

/**
 * How far a new workspace is from taking real calls, for the setup checklist:
 * has any agent been tried (a test call counts), and can callers reach one.
 * `agent` is the newest agent, the one the checklist's links open.
 */
export interface SetupProgress {
    tested: boolean;
    connected: boolean;
    agent: WorkflowListResponse | null;
}

export function setupProgress(agents: WorkflowListResponse[]): SetupProgress {
    return {
        tested: agents.some((agent) => (agent.total_runs ?? 0) > 0),
        connected: agents.some((agent) => (agent.channels?.length ?? 0) > 0),
        agent: agents.reduce<WorkflowListResponse | null>(
            (newest, agent) => (newest && time(newest.created_at) >= time(agent.created_at) ? newest : agent),
            null,
        ),
    };
}

/** Call time as the stat strip shows it: "6 h 12 m", "45 m", "< 1 m". */
export function formatTalkTime(seconds: number): string {
    if (seconds <= 0) return '0 m';
    const minutes = Math.floor(seconds / 60);
    if (minutes === 0) return '< 1 m';
    const hours = Math.floor(minutes / 60);
    if (hours === 0) return `${minutes} m`;
    return minutes % 60 === 0 ? `${hours} h` : `${hours} h ${minutes % 60} m`;
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
    if (!value) return 'No calls yet';
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
