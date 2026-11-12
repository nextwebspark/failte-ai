import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ReportOverviewResponse } from '@/client/types.gen';

import { CSV_HEADERS, csvCell } from './csv';
import ReportsPage from './page';

const mocks = vi.hoisted(() => ({
    overview: vi.fn(),
    calls: vi.fn(),
    emailMe: vi.fn(),
    save: vi.fn(),
    reset: vi.fn(),
    auth: { isAuthenticated: true },
    perms: ['reports:read', 'agents:facts'] as string[],
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
    getReportOverviewApiV1OrganizationsReportsOverviewGet: mocks.overview,
    getReportCallsApiV1OrganizationsReportsCallsGet: mocks.calls,
    emailMeThisReportApiV1OrganizationsReportsEmailMePost: mocks.emailMe,
    saveReportLayoutApiV1OrganizationsReportsLayoutPut: mocks.save,
    resetReportLayoutApiV1OrganizationsReportsLayoutDelete: mocks.reset,
    getBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsGet: vi.fn(),
    updateBusinessFactsApiV1WorkflowWorkflowIdBusinessFactsPut: vi.fn(),
    markFollowUpDoneApiV1FollowUpsRunIdDonePost: vi.fn(),
}));
vi.mock('@/lib/auth', () => ({ useAuth: () => mocks.auth }));
vi.mock('@/context/OrgConfigContext', () => ({
    useOrgConfig: () => ({ can: (p: string) => mocks.perms.includes(p) }),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const card = (key: string, title: string, size: 'kpi' | 'panel' | 'wide', extra: Partial<{ on: boolean; email: boolean; estimate: boolean }> = {}) => ({
    key,
    title,
    size,
    on: true,
    email: false,
    estimate: false,
    ...extra,
});

function overview(over: Partial<ReportOverviewResponse> = {}): ReportOverviewResponse {
    const cards = [
        card('calls_answered', 'Calls answered', 'kpi', { email: true }),
        card('covers_booked', 'Covers booked', 'kpi'),
        card('bookings_value', 'Bookings value', 'kpi', { estimate: true }),
        card('unanswered_questions', "Questions your agent couldn't answer", 'panel'),
        card('special_requests', 'Special requests', 'panel', { on: false }),
    ];
    return {
        range: '7d',
        timezone: 'Europe/Dublin',
        workflow_id: null,
        start: '2026-11-01T00:00:00Z',
        end: '2026-11-07T15:00:00Z',
        previous_start: '2026-10-25T00:00:00Z',
        previous_end: '2026-11-01T00:00:00Z',
        template: 'restaurant',
        pack: 'restaurant',
        pack_label: 'Restaurant',
        calls: 112,
        has_calls: true,
        agents: [{ id: 18, name: 'Linen Quay', active: true }],
        layout: {
            cards,
            defaults: cards,
            average: null,
            value_unit: 'cover',
            value_label: 'Average spend per cover',
            customised: false,
            updated_at: null,
            updated_by: null,
            can_customise: true,
        },
        cards: {
            calls_answered: { calls: 112, previous: 98, change: 14, after_hours: 18 },
            covers_booked: {
                covers: 142,
                previous: 121,
                change: 21,
                bookings_with_size: 38,
                not_given: 1,
                unreadable: 1,
                average_party: 3.7,
            },
            bookings_value: null,
            unanswered_questions: {
                calls: 4,
                groups: [
                    {
                        question: 'Do you have gluten-free pasta?',
                        count: 4,
                        run_id: 9,
                        workflow_id: 18,
                        last_asked_at: '2026-11-06T12:00:00Z',
                        answered: false,
                    },
                ],
                more: 0,
            },
            special_requests: { tags: [], calls_with_requests: 0, tagged_calls: 0, not_tagged: 3 },
        },
        ...over,
    } as ReportOverviewResponse;
}

describe('ReportsPage', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.perms = ['reports:read', 'agents:facts'];
        mocks.overview.mockResolvedValue({ data: overview() });
        mocks.calls.mockResolvedValue({
            data: {
                timezone: 'Europe/Dublin',
                start: '2026-11-01T00:00:00Z',
                end: '2026-11-07T15:00:00Z',
                calls: [
                    {
                        run_id: 9,
                        workflow_id: 18,
                        workflow_name: 'Linen Quay',
                        created_at: '2026-11-02T12:05:00Z',
                        caller_number: '+353 1 "main"',
                        caller_name: null,
                        result: 'booking_made',
                        reason_label: 'Reservations',
                        duration_seconds: 61.4,
                    },
                ],
            },
        });
    });

    it('shows the pack, the period and the cards that are on, from real numbers', async () => {
        render(<ReportsPage />);
        expect(await screen.findByRole('heading', { name: 'Last 7 days, 1–7 Nov' })).toBeTruthy();
        expect(screen.getByText(/Reports · Restaurant pack/)).toBeTruthy();
        expect(screen.getByText(/Compared with the 7 days before/)).toBeTruthy();
        const covers = screen.getByRole('region', { name: 'Covers booked' });
        expect(within(covers).getByText('142')).toBeTruthy();
        expect(within(covers).getByText('↑ 21')).toBeTruthy();
        expect(within(covers).getByText(/2 bookings without a clear party size, not counted/)).toBeTruthy();
        expect(screen.getByText('18 came in while you were closed')).toBeTruthy();
        // Switched off: not shown.
        expect(screen.queryByRole('region', { name: 'Special requests' })).toBeNull();
        expect(mocks.overview).toHaveBeenCalledWith({ query: { range: '7d', workflow_id: undefined } });
    });

    it('never shows money without the owner’s own average', async () => {
        render(<ReportsPage />);
        await screen.findByRole('heading', { name: 'Last 7 days, 1–7 Nov' });
        expect(screen.queryByText('Bookings value')).toBeNull();
        expect(screen.queryByText(/€/)).toBeNull();
    });

    it('labels an estimate and writes out its sum', async () => {
        const base = overview();
        mocks.overview.mockResolvedValue({
            data: overview({
                layout: { ...base.layout, average: '35.00' },
                cards: {
                    ...base.cards,
                    bookings_value: {
                        average: '35.00',
                        units: 142,
                        unit: 'cover',
                        value: '4970',
                        previous_value: '4235',
                        change: '735',
                    },
                },
            }),
        });
        render(<ReportsPage />);
        const value = await screen.findByRole('region', { name: 'Bookings value' });
        expect(within(value).getByText('€4,970')).toBeTruthy();
        expect(within(value).getByText('Estimate')).toBeTruthy();
        expect(within(value).getByText('Estimate: 142 covers × your €35 average spend')).toBeTruthy();
    });

    it('offers Add an answer only to members who can change the answers', async () => {
        render(<ReportsPage />);
        expect(await screen.findByRole('button', { name: 'Add an answer' })).toBeTruthy();
        fireEvent.click(screen.getByRole('button', { name: 'Add an answer' }));
        expect(await screen.findByRole('dialog')).toBeTruthy();
    });

    it('staff see the same report without Customise or Add an answer', async () => {
        mocks.perms = ['reports:read'];
        const base = overview();
        mocks.overview.mockResolvedValue({ data: overview({ layout: { ...base.layout, can_customise: false } }) });
        render(<ReportsPage />);
        await screen.findByRole('heading', { name: 'Last 7 days, 1–7 Nov' });
        expect(screen.queryByRole('button', { name: 'Customise' })).toBeNull();
        expect(screen.queryByRole('button', { name: 'Add an answer' })).toBeNull();
        expect(screen.getByRole('region', { name: 'Covers booked' })).toBeTruthy();
    });

    it('customise: move a card with the keyboard, switch one on, and save for everyone', async () => {
        const base = overview();
        mocks.save.mockResolvedValue({ data: { ...base.layout, customised: true } });
        render(<ReportsPage />);
        fireEvent.click(await screen.findByRole('button', { name: 'Customise' }));
        const handle = await screen.findByRole('button', { name: /Move Covers booked, position 2 of 5/ });
        fireEvent.keyDown(handle, { key: 'ArrowUp' });
        fireEvent.click(screen.getByRole('switch', { name: 'Show Special requests' }));
        fireEvent.change(screen.getByLabelText('Average spend per cover'), { target: { value: '35' } });
        fireEvent.click(screen.getByRole('button', { name: 'Save' }));
        await waitFor(() => expect(mocks.save).toHaveBeenCalled());
        const body = mocks.save.mock.calls[0][0].body;
        expect(body.cards.map((c: { key: string }) => c.key).slice(0, 2)).toEqual(['covers_booked', 'calls_answered']);
        expect(body.cards.find((c: { key: string }) => c.key === 'special_requests').on).toBe(true);
        expect(body.average).toBe('35');
        expect(toast.success).toHaveBeenCalled();
    });

    it('resets to the pack', async () => {
        mocks.reset.mockResolvedValue({ data: overview().layout });
        render(<ReportsPage />);
        fireEvent.click(await screen.findByRole('button', { name: 'Customise' }));
        fireEvent.click(await screen.findByRole('button', { name: /Reset to the Restaurant pack/ }));
        await waitFor(() => expect(mocks.reset).toHaveBeenCalled());
        expect(toast.success).toHaveBeenCalledWith('Back to the Restaurant pack.');
    });

    it('switches period and asks again', async () => {
        render(<ReportsPage />);
        await screen.findByRole('heading', { name: 'Last 7 days, 1–7 Nov' });
        fireEvent.click(screen.getByRole('button', { name: '30 days' }));
        await waitFor(() => expect(mocks.overview).toHaveBeenLastCalledWith({ query: { range: '30d', workflow_id: undefined } }));
    });

    it('shows an API error with Try again, then recovers', async () => {
        mocks.overview.mockResolvedValue({ error: { detail: 'boom' } });
        render(<ReportsPage />);
        expect((await screen.findByRole('alert')).textContent).toContain("We couldn't load this report");
        mocks.overview.mockResolvedValue({ data: overview() });
        fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
        expect(await screen.findByRole('heading', { name: 'Last 7 days, 1–7 Nov' })).toBeTruthy();
    });

    it('guides a business with no calls yet', async () => {
        mocks.overview.mockResolvedValue({ data: overview({ has_calls: false, calls: 0 }) });
        render(<ReportsPage />);
        expect(await screen.findByText('No calls yet')).toBeTruthy();
    });

    it('downloads the calls in range with plain column names', async () => {
        const createObjectURL = vi.fn((blob: Blob) => {
            void blob;
            return 'blob:x';
        });
        vi.stubGlobal('URL', Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }));
        const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
        render(<ReportsPage />);
        fireEvent.click(await screen.findByRole('button', { name: 'Download' }));
        await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Your calls are downloading.'));
        const csv = await (createObjectURL.mock.calls[0][0] as Blob).text();
        const [header, row] = csv.split('\n');
        expect(header).toBe(CSV_HEADERS.map(csvCell).join(','));
        expect(row).toContain('"Booking made"');
        expect(row).toContain('"+353 1 ""main"""');
        expect(row).toContain('/workflow/18/run/9');
        expect(mocks.calls).toHaveBeenCalledWith({ query: { range: '7d', workflow_id: undefined } });
        click.mockRestore();
    });

    it('tells the user when there is nothing to download', async () => {
        mocks.calls.mockResolvedValue({ data: { timezone: 'Europe/Dublin', start: '', end: '', calls: [] } });
        render(<ReportsPage />);
        fireEvent.click(await screen.findByRole('button', { name: 'Download' }));
        await waitFor(() => expect(toast.info).toHaveBeenCalledWith('There are no calls to download for this period.'));
    });

    it('shows a toast when the download fails', async () => {
        mocks.calls.mockResolvedValue({ error: { detail: 'nope' } });
        render(<ReportsPage />);
        fireEvent.click(await screen.findByRole('button', { name: 'Download' }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Couldn't download the calls. Please try again."));
    });
    it('emails the report on screen to the member asking', async () => {
        mocks.emailMe.mockResolvedValue({ data: { sent_to: 'niamh@example.ie' } });
        render(<ReportsPage />);
        fireEvent.click(await screen.findByRole('button', { name: 'Email me' }));
        await waitFor(() => expect(mocks.emailMe).toHaveBeenCalledTimes(1));
        // The same days and agent as the report on screen.
        expect(mocks.emailMe.mock.calls[0][0]).toEqual({ query: mocks.overview.mock.calls.at(-1)?.[0].query });
        await waitFor(() => expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('niamh@example.ie')));
    });
});
