import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { CallerDataRequestDialog } from './CallerDataRequestDialog';

const mocks = vi.hoisted(() => ({ exportCallerData: vi.fn(), eraseCallerData: vi.fn() }));

vi.mock('@/client/sdk.gen', () => ({
    exportCallerDataApiV1OrganizationsUsageSubjectDataExportPost: mocks.exportCallerData,
    eraseCallerDataApiV1OrganizationsUsageSubjectDataErasePost: mocks.eraseCallerData,
}));

const erasure = {
    number: '+353871234567',
    calls_erased: 3,
    calls_in_progress: [41],
    calls_failed: [],
    objects_deleted: 15,
    queued_calls_deleted: 1,
    queued_calls_cleared: 1,
    queued_calls_in_progress: 0,
    campaign_lists_rewritten: 1,
    campaign_list_rows_removed: 1,
    campaign_lists_failed: [],
};

function openWithNumber(number: string) {
    render(<CallerDataRequestDialog />);
    fireEvent.click(screen.getByRole('button', { name: 'Caller data request' }));
    fireEvent.change(screen.getByLabelText("Caller's phone number"), { target: { value: number } });
}

describe('CallerDataRequestDialog', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        window.URL.createObjectURL = vi.fn(() => 'blob:caller-data');
        window.URL.revokeObjectURL = vi.fn();
    });

    it('downloads the caller data as JSON', async () => {
        mocks.exportCallerData.mockResolvedValue({
            data: {
                number: '+353871234567',
                generated_at: '2026-10-21T08:00:00Z',
                signed_urls_expire_in: 3600,
                calls: [{ id: 1 }, { id: 2 }],
                queued_calls: [{ id: 9 }],
                truncated: false,
            },
        });
        const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
        openWithNumber(' +353 87 123 4567 ');

        fireEvent.click(screen.getByRole('button', { name: 'Download data (JSON)' }));

        expect(await screen.findByText(/Downloaded 2 calls and 1 campaign contact for \+353871234567/)).toBeTruthy();
        expect(mocks.exportCallerData).toHaveBeenCalledWith({ body: { number: '+353 87 123 4567' } });
        expect(click).toHaveBeenCalled();
    });

    it("shows why a number can't be used", async () => {
        mocks.exportCallerData.mockResolvedValue({
            error: { detail: "That is one of your organization's own numbers. Enter the caller's number." },
        });
        openWithNumber('+35315550000');

        fireEvent.click(screen.getByRole('button', { name: 'Download data (JSON)' }));

        expect((await screen.findByRole('alert')).textContent).toContain('own numbers');
    });

    it('erases the caller data after confirmation and shows what was done', async () => {
        mocks.eraseCallerData.mockResolvedValue({ data: erasure });
        openWithNumber('+353871234567');

        fireEvent.click(screen.getByRole('button', { name: 'Erase all data' }));
        const confirm = await screen.findByRole('alertdialog');
        expect(mocks.eraseCallerData).not.toHaveBeenCalled();
        fireEvent.click(
            screen.getAllByRole('button', { name: 'Erase all data' }).find((button) => confirm.contains(button))!,
        );

        await waitFor(() => expect(screen.getByText('Erased data for +353871234567')).toBeTruthy());
        expect(mocks.eraseCallerData).toHaveBeenCalledWith({ body: { number: '+353871234567' } });
        expect(screen.getByText('3 calls erased (15 stored files deleted)')).toBeTruthy();
        expect(screen.getByText('1 row removed from 1 contact list')).toBeTruthy();
        expect(screen.getByText(/1 call still in progress \(41\) was skipped/)).toBeTruthy();
    });
});
