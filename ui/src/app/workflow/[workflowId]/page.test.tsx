import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import WorkflowDetailPage from './page';

const mocks = vi.hoisted(() => ({
    query: 'version=3',
    auth: { user: { id: '1' }, loading: false, redirectToLogin: vi.fn() },
    workflow: vi.fn(),
    versions: vi.fn(),
    replace: vi.fn(),
    openTester: vi.fn(),
}));

vi.mock('next/navigation', () => ({
    useParams: () => ({ workflowId: '12' }),
    useSearchParams: () => new URLSearchParams(mocks.query),
    usePathname: () => '/workflow/12',
    useRouter: () => ({ replace: mocks.replace }),
}));
vi.mock('@/lib/auth', () => ({ useAuth: () => mocks.auth }));
vi.mock('@/lib/logger', () => ({ default: { error: vi.fn() } }));
vi.mock('posthog-js', () => ({ default: { capture: vi.fn() } }));
vi.mock('@/client/sdk.gen', () => ({
    getWorkflowApiV1WorkflowFetchWorkflowIdGet: mocks.workflow,
    getWorkflowVersionsApiV1WorkflowWorkflowIdVersionsGet: mocks.versions,
}));
vi.mock('../WorkflowLayout', () => ({ default: ({ children }: { children: ReactNode }) => children }));
vi.mock('@/context/AgentShellContext', () => ({ useAgentShell: () => ({ openTester: mocks.openTester }) }));
vi.mock('./RenderWorkflow', () => ({
    default: (props: Record<string, unknown>) => <pre data-testid="workflow">{JSON.stringify(props)}</pre>,
}));

const version = (number: number) => ({
    id: 100 + number,
    version_number: number,
    status: 'archived',
    workflow_json: { nodes: [{ id: `v${number}` }], edges: [] },
    workflow_configurations: { max_call_duration: number * 100 },
    template_context_variables: { company: `Version ${number}` },
});

const editorProps = () => JSON.parse(screen.getByTestId('workflow').textContent!);

beforeEach(() => {
    vi.clearAllMocks();
    mocks.query = 'version=3';
    mocks.auth.loading = false;
    mocks.workflow.mockResolvedValue({ data: {
        id: 12,
        name: 'Agent',
        workflow_definition: { nodes: [{ id: 'draft' }], edges: [] },
        workflow_configurations: { max_call_duration: 999 },
        template_context_variables: { company: 'Draft' },
        version_number: 20,
        version_status: 'draft',
    } });
    mocks.versions.mockResolvedValue({ data: [version(3)] });
});

describe('workflow version links', () => {
    it('loads the exact graph, configurations and variables without loading history', async () => {
        render(<WorkflowDetailPage />);
        await screen.findByTestId('workflow');
        expect(mocks.versions).toHaveBeenCalledWith({
            path: { workflow_id: 12 }, query: { version_number: 3, limit: 1 },
        });
        expect(editorProps().initialSelectedVersion.id).toBe(103);
        expect(editorProps().initialFlow.nodes).toEqual([{ id: 'v3' }]);
        expect(editorProps().initialWorkflowConfigurations).toEqual({ max_call_duration: 300 });
        expect(editorProps().initialTemplateContextVariables).toEqual({ company: 'Version 3' });
        expect(editorProps().initialVersionStatus).toBe('draft');
    });

    it('resolves latest to published even when an editable draft exists', async () => {
        mocks.query = 'version=latest';
        render(<WorkflowDetailPage />);
        await screen.findByTestId('workflow');
        expect(mocks.versions).toHaveBeenCalledWith({
            path: { workflow_id: 12 }, query: { status: 'published', limit: 1 },
        });
        expect(editorProps().initialFlow.nodes).toEqual([{ id: 'v3' }]);
    });

    it('waits for authentication before fetching either resource', async () => {
        mocks.auth.loading = true;
        const view = render(<WorkflowDetailPage />);
        expect(mocks.workflow).not.toHaveBeenCalled();
        expect(mocks.versions).not.toHaveBeenCalled();
        mocks.auth.loading = false;
        view.rerender(<WorkflowDetailPage />);
        await screen.findByTestId('workflow');
    });

    it.each(['', '0', '-1', 'abc', '1.5'])('rejects invalid version %j without opening the draft', async value => {
        mocks.query = `version=${value}`;
        render(<WorkflowDetailPage />);
        await screen.findByText(/Invalid version\./);
        expect(mocks.workflow).not.toHaveBeenCalled();
        expect(screen.queryByTestId('workflow')).toBeNull();
    });

    it('shows a missing version instead of silently opening the draft', async () => {
        mocks.versions.mockResolvedValue({ data: [] });
        render(<WorkflowDetailPage />);
        await screen.findByText('Version not found');
        expect(screen.queryByTestId('workflow')).toBeNull();
    });

    it('follows query changes and restores the default editor when the parameter is removed', async () => {
        const view = render(<WorkflowDetailPage />);
        await screen.findByTestId('workflow');
        mocks.query = 'version=1';
        mocks.versions.mockResolvedValue({ data: [version(1)] });
        view.rerender(<WorkflowDetailPage />);
        await waitFor(() => expect(editorProps().initialSelectedVersion.id).toBe(101));
        mocks.query = '';
        view.rerender(<WorkflowDetailPage />);
        await waitFor(() => expect(editorProps().initialFlow.nodes).toEqual([{ id: 'draft' }]));
        expect(editorProps().initialSelectedVersion).toBeUndefined();
        expect(mocks.versions).toHaveBeenCalledTimes(2);
    });

    it('ignores a slow response for a version the user has left', async () => {
        let resolveOld!: (value: unknown) => void;
        mocks.versions.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }));
        const view = render(<WorkflowDetailPage />);
        await waitFor(() => expect(mocks.versions).toHaveBeenCalledTimes(1));
        mocks.query = 'version=1';
        mocks.versions.mockResolvedValue({ data: [version(1)] });
        view.rerender(<WorkflowDetailPage />);
        await screen.findByTestId('workflow');
        await act(async () => { resolveOld({ data: [version(3)] }); });
        expect(editorProps().initialSelectedVersion.id).toBe(101);
    });
});

describe('arriving from the Create agent wizard', () => {
    it('opens the tester once and drops the onboarding flag from the URL', async () => {
        mocks.query = 'onboarding=web_call';
        render(<WorkflowDetailPage />);
        await screen.findByTestId('workflow');

        expect(editorProps().openTesterOnLoad).toBe(true);
        // A refresh or Back must not open the tester again.
        expect(mocks.replace).toHaveBeenCalledWith('/workflow/12', { scroll: false });
    });

    it('keeps the other query parameters when it drops the flag', async () => {
        mocks.query = 'version=3&onboarding=web_call';
        render(<WorkflowDetailPage />);
        await screen.findByTestId('workflow');

        expect(mocks.replace).toHaveBeenCalledWith('/workflow/12?version=3', { scroll: false });
    });

    it('leaves the URL and the tester alone otherwise', async () => {
        mocks.query = '';
        render(<WorkflowDetailPage />);
        await screen.findByTestId('workflow');

        expect(editorProps().openTesterOnLoad).toBe(false);
        expect(mocks.replace).not.toHaveBeenCalled();
    });
});

function setScreenWidth(small: boolean) {
    Object.defineProperty(window, 'matchMedia', {
        configurable: true,
        writable: true,
        value: (query: string) => ({
            matches: small,
            media: query,
            addEventListener: vi.fn(),
            removeEventListener: vi.fn(),
        }),
    });
}

describe('on a phone', () => {
    afterEach(() => {
        // jsdom has no matchMedia of its own; put it back to "missing".
        delete (window as { matchMedia?: unknown }).matchMedia;
    });

    it('shows a friendly note instead of the diagram, with a way through', async () => {
        mocks.query = '';
        setScreenWidth(true);
        render(<WorkflowDetailPage />);

        expect(await screen.findByRole('heading', { name: /easier on a bigger screen/i })).toBeTruthy();
        expect(screen.queryByTestId('workflow')).toBeNull();
        expect(screen.getByRole('link', { name: /go to business facts/i }).getAttribute('href')).toBe('/workflow/12/facts');

        fireEvent.click(screen.getByRole('button', { name: /talk to your agent/i }));
        expect(mocks.openTester).toHaveBeenCalled();

        fireEvent.click(screen.getByRole('button', { name: /show the diagram anyway/i }));
        expect(await screen.findByTestId('workflow')).toBeTruthy();
    });

    it('opens the diagram straight away on a bigger screen', async () => {
        mocks.query = '';
        setScreenWidth(false);
        render(<WorkflowDetailPage />);
        expect(await screen.findByTestId('workflow')).toBeTruthy();
        expect(screen.queryByRole('heading', { name: /easier on a bigger screen/i })).toBeNull();
    });
});

describe('when the agent cannot load', () => {
    it('says so in plain words and offers Try again', async () => {
        mocks.query = '';
        mocks.workflow.mockResolvedValueOnce({ error: { detail: 'Internal Server Error: boom' }, response: { status: 500 } });
        render(<WorkflowDetailPage />);

        const alert = await screen.findByRole('alert');
        expect(alert.textContent).toContain("We couldn't load this agent");
        expect(alert.textContent).not.toContain('boom');

        fireEvent.click(screen.getByRole('button', { name: /try again/i }));
        expect(await screen.findByTestId('workflow')).toBeTruthy();
    });

    it('explains a missing agent without a pointless retry', async () => {
        mocks.query = '';
        mocks.workflow.mockResolvedValueOnce({ error: { detail: 'Not found' }, response: { status: 404 } });
        render(<WorkflowDetailPage />);

        expect((await screen.findByRole('alert')).textContent).toContain("We couldn't find this agent");
        expect(screen.queryByRole('button', { name: /try again/i })).toBeNull();
    });
});
