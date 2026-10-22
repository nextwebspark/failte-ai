import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { WorkflowListResponse } from '@/client/types.gen';

vi.mock('next/navigation', () => ({
    useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
    usePathname: () => '/workflow',
    useSearchParams: () => new URLSearchParams(),
}));
vi.mock('@/components/workflow/CreateWorkflowButton', () => ({
    CreateWorkflowButton: () => <button type="button">Create agent</button>,
}));
vi.mock('@/components/workflow/UploadWorkflowButton', () => ({
    UploadWorkflowButton: ({ label = 'Import agent' }: { label?: string }) => <button type="button">{label}</button>,
}));
vi.mock('@/components/workflow/WorkflowTable', () => ({
    WorkflowTable: ({ workflows }: { workflows: WorkflowListResponse[] }) => (
        <ul>{workflows.map((w) => <li key={w.id}>{w.name}</li>)}</ul>
    ),
}));
// The onboarding store, held in memory so a dismissal outlives a remount.
const seenTooltips = new Set<string>();
vi.mock('@/context/OnboardingContext', async () => {
    const { useState } = await import('react');
    return {
        useOnboarding: () => {
            const [, rerender] = useState(0);
            return {
                hasSeenTooltip: (key: string) => seenTooltips.has(key),
                markTooltipSeen: (key: string) => {
                    seenTooltips.add(key);
                    rerender((n) => n + 1);
                },
            };
        },
    };
});
vi.mock('@/components/workflow/folders/AgentFolderView', () => ({
    AgentFolderView: ({ workflows }: { workflows: WorkflowListResponse[] }) => (
        <ul>{workflows.map((w) => <li key={w.id}>{w.name}</li>)}</ul>
    ),
}));

const { AgentList } = await import('./AgentList');

function agent(overrides: Partial<WorkflowListResponse> = {}): WorkflowListResponse {
    return {
        id: 7,
        name: 'Harbour Vets reception',
        status: 'active',
        created_at: '2026-10-20T09:00:00Z',
        total_runs: 0,
        runs_7d: [0, 0, 0, 0, 0, 0, 0],
        last_run_at: null,
        has_draft: false,
        channels: [],
        ...overrides,
    };
}

function renderList(active: WorkflowListResponse[]) {
    return render(<AgentList activeWorkflows={active} archivedWorkflows={[]} folders={[]} />);
}

beforeEach(() => {
    seenTooltips.clear();
});

describe('AgentList for a new workspace', () => {
    it('welcomes a workspace with no agents and explains the steps', () => {
        renderList([]);
        expect(screen.getByRole('heading', { name: 'Create your first agent' })).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Import an agent' })).toBeTruthy();
        expect(screen.getAllByRole('listitem')).toHaveLength(3);
        expect(screen.queryByText('Live now')).toBeNull();
    });

    it('shows the setup checklist instead of zero stats until a first call', () => {
        renderList([agent()]);
        expect(screen.getByRole('heading', { name: 'Get your agent ready for calls' })).toBeTruthy();
        expect(screen.getByText('1 of 3 done')).toBeTruthy();
        expect(screen.getByRole('link', { name: 'Talk to your agent' }).getAttribute('href')).toBe('/workflow/7');
        expect(screen.getByRole('link', { name: 'Add a phone number' }).getAttribute('href')).toBe('/workflow/7/deployment#phone');
        expect(screen.getByRole('link', { name: 'Add to your website' }).getAttribute('href')).toBe('/workflow/7/deployment#website');
        expect(screen.queryByText('Live now')).toBeNull();
        // One agent: nothing to search or sort yet.
        expect(screen.queryByLabelText('Search agents')).toBeNull();
    });

    it('shows the stats beside the checklist once a call has happened', () => {
        renderList([agent({ total_runs: 2 }), agent({ id: 8, name: 'After hours' })]);
        expect(screen.getByText('2 of 3 done')).toBeTruthy();
        expect(screen.getByText('Live now')).toBeTruthy();
        expect(screen.getByLabelText('Search agents')).toBeTruthy();
    });

    it('drops the checklist once an agent is tested and reachable', () => {
        renderList([agent({ total_runs: 2, channels: ['phone'] })]);
        expect(screen.queryByRole('heading', { name: 'Get your agent ready for calls' })).toBeNull();
        expect(screen.getByText('Live now')).toBeTruthy();
    });

    it('remembers when the checklist is hidden', () => {
        const { unmount } = renderList([agent()]);
        fireEvent.click(screen.getByRole('button', { name: 'Hide setup steps' }));
        expect(screen.queryByRole('heading', { name: 'Get your agent ready for calls' })).toBeNull();
        expect(screen.getByText('Live now')).toBeTruthy();
        unmount();
        renderList([agent()]);
        expect(screen.queryByRole('heading', { name: 'Get your agent ready for calls' })).toBeNull();
    });
});
