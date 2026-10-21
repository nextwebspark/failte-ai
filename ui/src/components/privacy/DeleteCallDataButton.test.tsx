import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DeleteCallDataButton } from './DeleteCallDataButton';

const mocks = vi.hoisted(() => ({ deleteRunData: vi.fn() }));

vi.mock('@/client/sdk.gen', () => ({
    deleteWorkflowRunDataApiV1WorkflowWorkflowIdRunsRunIdDelete: mocks.deleteRunData,
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

async function confirmDelete() {
    fireEvent.click(screen.getByRole('button', { name: 'Delete call data' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog.textContent).toContain('stays in your usage history');
    fireEvent.click(
        screen.getAllByRole('button', { name: 'Delete call data' }).find((button) => dialog.contains(button))!,
    );
}

describe('DeleteCallDataButton', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('deletes the call data after confirmation', async () => {
        mocks.deleteRunData.mockResolvedValue({ data: { run_id: 34, objects_deleted: 5 } });
        const onDeleted = vi.fn();
        render(<DeleteCallDataButton workflowId={12} runId={34} onDeleted={onDeleted} />);

        await confirmDelete();

        await waitFor(() => expect(onDeleted).toHaveBeenCalled());
        expect(mocks.deleteRunData).toHaveBeenCalledWith({ path: { workflow_id: 12, run_id: 34 } });
        expect(toast.success).toHaveBeenCalledWith('Call data deleted');
    });

    it('shows why the call data could not be deleted', async () => {
        mocks.deleteRunData.mockResolvedValue({
            error: { detail: 'This call is still in progress. Delete its data once it ends.' },
        });
        const onDeleted = vi.fn();
        render(<DeleteCallDataButton workflowId={12} runId={34} onDeleted={onDeleted} />);

        await confirmDelete();

        await waitFor(() => expect(toast.error).toHaveBeenCalledWith(
            'This call is still in progress. Delete its data once it ends.',
        ));
        expect(onDeleted).not.toHaveBeenCalled();
    });
});
