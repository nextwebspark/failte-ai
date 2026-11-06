import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { CSV_HEADERS, csvCell } from './csv';
import ReportsPage from './page';

const mocks = vi.hoisted(() => ({
    daily: vi.fn(),
    runs: vi.fn(),
    auth: { isAuthenticated: true },
}));

vi.stubGlobal(
    'ResizeObserver',
    class {
        observe() {}
        unobserve() {}
        disconnect() {}
    },
);

vi.mock('@/client/sdk.gen', () => ({
    getDailyReportApiV1OrganizationsReportsDailyGet: mocks.daily,
    getDailyRunsDetailApiV1OrganizationsReportsDailyRunsGet: mocks.runs,
    getPreferencesApiV1OrganizationsPreferencesGet: vi.fn(async () => ({ data: { timezone: 'Europe/Dublin' } })),
    getWorkflowOptionsApiV1OrganizationsReportsWorkflowsGet: vi.fn(async () => ({ data: [{ id: 4, name: 'Front desk' }] })),
}));
vi.mock('@/lib/auth', () => ({ useAuth: () => mocks.auth }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
vi.mock('./components/DispositionChart', () => ({ DispositionChart: () => <div>Call outcomes chart</div> }));
vi.mock('./components/DurationChart', () => ({ DurationChart: () => <div>Call length chart</div> }));
vi.mock('./components/MetricsCards', () => ({
    MetricsCards: ({ metrics }: { metrics: { total_runs: number } }) => <div>{metrics.total_runs} calls</div>,
}));

function report(total: number) {
    return {
        data: {
            date: '2026-11-05',
            timezone: 'Europe/Dublin',
            workflow_id: null,
            metrics: { total_runs: total, xfer_count: 0 },
            disposition_distribution: [],
            call_duration_distribution: [],
        },
    };
}

describe('ReportsPage', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.daily.mockResolvedValue(report(3));
        mocks.runs.mockResolvedValue({
            data: [{ workflow_id: 4, run_id: 9, phone_number: '+353 1 "main"', disposition: 'booked', duration_seconds: 61 }],
        });
        vi.spyOn(console, 'error').mockImplementation(() => {});
    });

    it('loads the day and shows the calls', async () => {
        render(<ReportsPage />);
        expect(await screen.findByText('3 calls')).toBeTruthy();
        expect(screen.getByText('Call outcomes chart')).toBeTruthy();
    });

    it('names the icon-only day buttons', async () => {
        render(<ReportsPage />);
        await screen.findByText('3 calls');
        expect(screen.getByRole('button', { name: 'Previous day' })).toBeTruthy();
        // Today: no next day yet.
        expect(screen.getByRole('button', { name: 'Next day' }).hasAttribute('disabled')).toBe(true);
    });

    it('goes back a day and loads it', async () => {
        render(<ReportsPage />);
        await screen.findByText('3 calls');
        const before = mocks.daily.mock.calls.length;
        fireEvent.click(screen.getByRole('button', { name: 'Previous day' }));
        await waitFor(() => expect(mocks.daily.mock.calls.length).toBeGreaterThan(before));
        const lastDate = mocks.daily.mock.calls.at(-1)?.[0].query.date;
        expect(lastDate).not.toBe(mocks.daily.mock.calls[0][0].query.date);
        expect(screen.getByRole('button', { name: 'Next day' }).hasAttribute('disabled')).toBe(false);
    });

    it('shows an API error with Try again, then recovers', async () => {
        mocks.daily.mockResolvedValue({ error: { detail: 'boom' } });
        render(<ReportsPage />);
        expect((await screen.findByRole('alert')).textContent).toContain("Couldn't load the report");
        mocks.daily.mockResolvedValue(report(2));
        fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
        expect(await screen.findByText('2 calls')).toBeTruthy();
        expect(screen.queryByRole('alert')).toBeNull();
    });

    it('handles a network failure while loading', async () => {
        mocks.daily.mockRejectedValue(new TypeError('Failed to fetch'));
        render(<ReportsPage />);
        expect((await screen.findByRole('alert')).textContent).toContain("Couldn't load the report");
        expect(screen.queryByText(/Failed to fetch/)).toBeNull();
    });

    it('says so plainly on a day with no calls, and offers no download', async () => {
        mocks.daily.mockResolvedValue(report(0));
        render(<ReportsPage />);
        expect(await screen.findByText(/^No calls on/)).toBeTruthy();
        expect(screen.queryByRole('button', { name: /Download/ })).toBeNull();
    });

    it('downloads the calls with plain column names and a toast, not alert()', async () => {
        const alert = vi.spyOn(window, 'alert').mockImplementation(() => {});
        const createObjectURL = vi.fn((blob: Blob) => {
            void blob;
            return 'blob:x';
        });
        vi.stubGlobal('URL', Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }));
        const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

        render(<ReportsPage />);
        fireEvent.click(await screen.findByRole('button', { name: 'Download calls (CSV)' }));

        await waitFor(() => expect(toast.success).toHaveBeenCalled());
        expect(click).toHaveBeenCalled();
        const csv = await (createObjectURL.mock.calls[0][0] as Blob).text();
        expect(csv.split('\n')[0]).toBe('"Phone number","Call outcome","Call length (seconds)","Link to call"');
        expect(csv).toContain('"+353 1 ""main"""');
        expect(csv).toContain('/workflow/4/run/9');
        expect(alert).not.toHaveBeenCalled();
        click.mockRestore();
    });

    it('tells the user when there is nothing to download', async () => {
        mocks.runs.mockResolvedValue({ data: [] });
        render(<ReportsPage />);
        fireEvent.click(await screen.findByRole('button', { name: 'Download calls (CSV)' }));
        await waitFor(() => expect(toast.info).toHaveBeenCalledWith('There are no calls to download for this day.'));
    });

    it('shows a toast when the download fails', async () => {
        const alert = vi.spyOn(window, 'alert').mockImplementation(() => {});
        mocks.runs.mockResolvedValue({ error: { detail: 'nope' } });
        render(<ReportsPage />);
        fireEvent.click(await screen.findByRole('button', { name: 'Download calls (CSV)' }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Couldn't download the calls. Please try again."));
        expect(alert).not.toHaveBeenCalled();
    });

    it('shows a toast when the download throws', async () => {
        mocks.runs.mockRejectedValue(new TypeError('Failed to fetch'));
        render(<ReportsPage />);
        fireEvent.click(await screen.findByRole('button', { name: 'Download calls (CSV)' }));
        await waitFor(() => expect(toast.error).toHaveBeenCalled());
    });

    it('blocks a second download while one is being prepared', async () => {
        let resolve: (value: unknown) => void = () => {};
        mocks.runs.mockReturnValue(new Promise((r) => (resolve = r)));
        render(<ReportsPage />);
        const button = await screen.findByRole('button', { name: 'Download calls (CSV)' });
        fireEvent.click(button);
        fireEvent.click(button);
        expect(await screen.findByRole('button', { name: 'Preparing…' })).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Preparing…' }).hasAttribute('disabled')).toBe(true);
        expect(mocks.runs).toHaveBeenCalledTimes(1);
        resolve({ data: [] });
        await waitFor(() => expect(toast.info).toHaveBeenCalled());
    });
});

describe('csv helpers', () => {
    it('quotes cells and doubles inner quotes', () => {
        expect(csvCell('plain')).toBe('"plain"');
        expect(csvCell('say "hi"')).toBe('"say ""hi"""');
        expect(csvCell('')).toBe('""');
    });

    it('uses plain column names', () => {
        expect(CSV_HEADERS).toEqual(['Phone number', 'Call outcome', 'Call length (seconds)', 'Link to call']);
    });
});
