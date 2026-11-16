import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { WorkflowListResponse } from '@/client/types.gen';

import { WorkflowTable } from './WorkflowTable';

const mocks = vi.hoisted(() => ({
    push: vi.fn(),
    refresh: vi.fn(),
    status: vi.fn(),
    move: vi.fn(),
    perms: [] as string[],
}));

vi.stubGlobal(
    'ResizeObserver',
    class {
        observe() {}
        unobserve() {}
        disconnect() {}
    },
);

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }) }));
vi.mock('@/client/sdk.gen', () => ({
    updateWorkflowStatusApiV1WorkflowWorkflowIdStatusPut: mocks.status,
    moveWorkflowToFolderApiV1WorkflowWorkflowIdFolderPut: mocks.move,
}));
vi.mock('@/context/OrgConfigContext', () => ({
    useOrgConfig: () => ({ can: (...required: string[]) => required.every((p) => mocks.perms.includes(p)) }),
}));
vi.mock('@/hooks/useOrganizationTimezone', () => ({ useOrganizationTimezone: () => 'UTC' }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function agent(id: number, name: string, overrides: Partial<WorkflowListResponse> = {}): WorkflowListResponse {
    return {
        id,
        name,
        status: 'active',
        created_at: '2026-10-01T10:00:00Z',
        total_runs: 3,
        runs_7d: [0, 1, 0, 0, 2, 0, 0],
        channels: ['phone'],
        folder_id: null,
        ...overrides,
    } as WorkflowListResponse;
}

const AGENTS = [agent(1, 'Front desk'), agent(2, 'After hours')];

function openMenu(name: string) {
    const trigger = screen.getByRole('button', { name: `Actions for ${name}` });
    fireEvent.keyDown(trigger, { key: 'Enter' });
}

describe('WorkflowTable', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.perms = ['agents:read', 'agents:write'];
        mocks.status.mockResolvedValue({ data: {} });
        mocks.move.mockResolvedValue({ data: {} });
    });

    it("makes each agent's name a real link to the agent", () => {
        render(<WorkflowTable workflows={AGENTS} showArchived={false} />);
        expect(screen.getByRole('link', { name: 'Front desk' }).getAttribute('href')).toBe('/overview?agent=1');
        expect(screen.getByRole('link', { name: 'After hours' }).getAttribute('href')).toBe('/overview?agent=2');
    });

    it('rows are plain list items: no role="link", no tabindex, menu not inside the link', () => {
        const { container } = render(<WorkflowTable workflows={AGENTS} showArchived={false} />);
        for (const li of Array.from(container.querySelectorAll('li'))) {
            expect(li.getAttribute('role')).toBeNull();
            expect(li.getAttribute('tabindex')).toBeNull();
        }
        const link = screen.getByRole('link', { name: 'Front desk' });
        expect(link.querySelector('button')).toBeNull();
        expect(screen.getByRole('button', { name: 'Actions for Front desk' }).closest('a')).toBeNull();
    });

    it.each([
        ['owner', ['agents:read', 'calls:read', 'reports:read', 'agents:facts']],
        ['staff', ['agents:read', 'calls:read', 'reports:read']],
    ])('hides the actions menu from the %s, who cannot change agents', (_role, perms) => {
        mocks.perms = perms;
        render(<WorkflowTable workflows={AGENTS} showArchived={false} folders={[]} />);
        expect(screen.queryByRole('button', { name: /Actions for/ })).toBeNull();
        // They can still open each agent.
        expect(screen.getByRole('link', { name: 'Front desk' })).toBeTruthy();
    });

    it('opens the menu from the keyboard, with Open as a link', async () => {
        render(<WorkflowTable workflows={AGENTS} showArchived={false} />);
        openMenu('Front desk');
        const open = await screen.findByRole('menuitem', { name: 'Open' });
        expect(open.getAttribute('href')).toBe('/overview?agent=1');
        expect(screen.getByRole('menuitem', { name: 'Archive' })).toBeTruthy();
        expect(mocks.push).not.toHaveBeenCalled();
    });

    it('archives an agent and refreshes the list', async () => {
        render(<WorkflowTable workflows={AGENTS} showArchived={false} />);
        openMenu('Front desk');
        fireEvent.click(await screen.findByRole('menuitem', { name: 'Archive' }));
        await waitFor(() =>
            expect(mocks.status).toHaveBeenCalledWith({ path: { workflow_id: 1 }, body: { status: 'archived' } }),
        );
        await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Agent archived'));
        expect(mocks.refresh).toHaveBeenCalled();
    });

    it('says so when archiving fails, and does not refresh', async () => {
        vi.spyOn(console, 'error').mockImplementation(() => {});
        mocks.status.mockResolvedValue({ error: { detail: 'nope' } });
        render(<WorkflowTable workflows={AGENTS} showArchived={false} />);
        openMenu('Front desk');
        fireEvent.click(await screen.findByRole('menuitem', { name: 'Archive' }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Failed to archive agent'));
        expect(mocks.refresh).not.toHaveBeenCalled();
    });

    it('offers Restore for archived agents', async () => {
        render(<WorkflowTable workflows={[agent(5, 'Old line', { status: 'archived' })]} showArchived />);
        openMenu('Old line');
        fireEvent.click(await screen.findByRole('menuitem', { name: 'Restore' }));
        await waitFor(() =>
            expect(mocks.status).toHaveBeenCalledWith({ path: { workflow_id: 5 }, body: { status: 'active' } }),
        );
    });
});
