import { describe, expect, it } from 'vitest';

import type { WorkflowListResponse } from '@/client/types.gen';
import {
    agentStats,
    agentStatus,
    filterAgents,
    formatLastCall,
    formatTalkTime,
    hasDraftEdits,
    percentChange,
    setupProgress,
    sortAgents,
    sparklinePoints,
} from '@/lib/agentList';

function agent(overrides: Partial<WorkflowListResponse>): WorkflowListResponse {
    return {
        id: 1,
        name: 'Agent',
        status: 'active',
        created_at: '2026-10-01T09:00:00Z',
        total_runs: 0,
        runs_7d: [0, 0, 0, 0, 0, 0, 0],
        last_run_at: null,
        has_draft: false,
        ...overrides,
    };
}

const reception = agent({
    id: 7,
    name: 'Dental reception',
    created_at: '2026-09-01T09:00:00Z',
    runs_7d: [1, 2, 0, 3, 4, 5, 6],
    last_run_at: '2026-10-17T11:58:00Z',
    talk_seconds_24h: 1500,
    live_calls: 1,
});
const reminders = agent({
    id: 8,
    name: 'booking reminders',
    created_at: '2026-10-10T09:00:00Z',
    runs_7d: [0, 0, 0, 0, 0, 2, 0],
    last_run_at: '2026-10-16T08:00:00Z',
    has_draft: true,
    talk_seconds_24h: 120,
});
const fresh = agent({ id: 9, name: 'After-hours triage', created_at: '2026-10-15T09:00:00Z' });

describe('agentList', () => {
    it('keeps an agent with a draft published, and flags the draft separately', () => {
        expect(agentStatus(reception)).toBe('published');
        expect(agentStatus(reminders)).toBe('published');
        expect(hasDraftEdits(reminders)).toBe(true);
        expect(hasDraftEdits(reception)).toBe(false);
        const archived = agent({ status: 'archived', has_draft: true });
        expect(agentStatus(archived)).toBe('archived');
        expect(hasDraftEdits(archived)).toBe(false);
    });

    it('filters by name, id as shown or typed, and draft edits', () => {
        const all = [reception, reminders, fresh, agent({ id: 123, name: 'Support' })];
        expect(filterAgents(all, '  BOOK ', 'all')).toEqual([reminders]);
        expect(filterAgents(all, '9', 'all')).toEqual([fresh]);
        expect(filterAgents(all, '#123', 'all').map((a) => a.id)).toEqual([123]);
        expect(filterAgents(all, '12', 'all').map((a) => a.id)).toEqual([123]);
        expect(filterAgents(all, '', 'draft')).toEqual([reminders]);
        expect(filterAgents(all, 'dental', 'draft')).toEqual([]);
    });

    it('sorts by last call, then newest for agents that never ran', () => {
        const all = [fresh, reminders, reception, agent({ id: 10, created_at: '2026-10-16T09:00:00Z' })];
        expect(sortAgents(all, 'last_call').map((a) => a.id)).toEqual([7, 8, 10, 9]);
        expect(sortAgents(all, 'name').map((a) => a.id)).toEqual([9, 10, 8, 7]);
        expect(sortAgents(all, 'newest').map((a) => a.id)).toEqual([10, 9, 8, 7]);
    });

    it('totals the stat strip', () => {
        expect(agentStats([reception, reminders, fresh])).toEqual({
            total: 3,
            withDraft: 1,
            callsToday: 6,
            callsYesterday: 7,
            talkSeconds: 1620,
            liveNow: 1,
        });
    });

    it('tracks setup: tried once any agent has a run, connected once one has a channel', () => {
        expect(setupProgress([])).toEqual({ tested: false, connected: false, agent: null });
        const untried = setupProgress([agent({ id: 1 }), agent({ id: 2, created_at: '2026-10-02T09:00:00Z' })]);
        expect(untried).toMatchObject({ tested: false, connected: false });
        expect(untried.agent?.id).toBe(2);
        const live = setupProgress([agent({ total_runs: 3, channels: ['web'] })]);
        expect(live).toMatchObject({ tested: true, connected: true });
    });

    it('words talk time in hours and minutes', () => {
        expect(formatTalkTime(0)).toBe('0 m');
        expect(formatTalkTime(40)).toBe('< 1 m');
        expect(formatTalkTime(45 * 60 + 20)).toBe('45 m');
        expect(formatTalkTime(2 * 3600)).toBe('2 h');
        expect(formatTalkTime(6 * 3600 + 12 * 60 + 5)).toBe('6 h 12 m');
    });

    it('reports percent change only when there is a base', () => {
        expect(percentChange(0, 5)).toBeNull();
        expect(percentChange(8, 10)).toBe(25);
        expect(percentChange(10, 7)).toBe(-30);
    });

    it('words the last call relative to now in the org timezone', () => {
        const now = new Date('2026-10-17T12:00:00Z');
        const tz = 'Europe/Dublin';
        expect(formatLastCall(null, tz, now)).toBe('No calls yet');
        expect(formatLastCall('2026-10-17T11:59:40Z', tz, now)).toBe('Just now');
        expect(formatLastCall('2026-10-17T11:48:00Z', tz, now)).toBe('12 min ago');
        expect(formatLastCall('2026-10-17T06:40:00Z', tz, now)).toBe('Today, 07:40');
        expect(formatLastCall('2026-10-16T08:00:00Z', tz, now)).toBe('Yesterday');
        expect(formatLastCall('2026-10-02T08:00:00Z', tz, now)).toBe('Oct 2, 2026');
        // 23:30 UTC on the 16th is already the 17th in Kolkata.
        expect(formatLastCall('2026-10-16T23:30:00Z', 'Asia/Kolkata', now)).toBe('Today, 05:00');
    });

    it('scales sparkline points to the box', () => {
        expect(sparklinePoints([])).toBe('');
        expect(sparklinePoints([0, 0, 0], 10, 10, 1)).toBe('1,9 5,9 9,9');
        expect(sparklinePoints([0, 2, 4], 10, 10, 1)).toBe('1,9 5,5 9,1');
    });
});
