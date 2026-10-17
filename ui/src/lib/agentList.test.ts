import { describe, expect, it } from 'vitest';

import type { WorkflowListResponse } from '@/client/types.gen';
import {
    agentStats,
    agentStatus,
    filterAgents,
    formatLastCall,
    percentChange,
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
});
const reminders = agent({
    id: 8,
    name: 'booking reminders',
    created_at: '2026-10-10T09:00:00Z',
    runs_7d: [0, 0, 0, 0, 0, 2, 0],
    last_run_at: '2026-10-16T08:00:00Z',
    has_draft: true,
});
const fresh = agent({ id: 9, name: 'After-hours triage', created_at: '2026-10-15T09:00:00Z' });

describe('agentList', () => {
    it('derives the status from archive state and drafts', () => {
        expect(agentStatus(reception)).toBe('published');
        expect(agentStatus(reminders)).toBe('draft');
        expect(agentStatus(agent({ status: 'archived', has_draft: true }))).toBe('archived');
    });

    it('filters by name, exact id and status', () => {
        const all = [reception, reminders, fresh];
        expect(filterAgents(all, '  BOOK ', 'all')).toEqual([reminders]);
        expect(filterAgents(all, '9', 'all')).toEqual([fresh]);
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
            published: 2,
            callsToday: 6,
            callsYesterday: 7,
            callsWeek: 23,
            lastCallAt: '2026-10-17T11:58:00Z',
        });
    });

    it('reports percent change only when there is a base', () => {
        expect(percentChange(0, 5)).toBeNull();
        expect(percentChange(8, 10)).toBe(25);
        expect(percentChange(10, 7)).toBe(-30);
    });

    it('words the last call relative to now in the org timezone', () => {
        const now = new Date('2026-10-17T12:00:00Z');
        const tz = 'Europe/Dublin';
        expect(formatLastCall(null, tz, now)).toBe('Never');
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
