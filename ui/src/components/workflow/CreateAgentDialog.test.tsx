import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

import { handOffOAuthReturn } from '@/app/integrations/oauthPopup';

import { CreateAgentDialog, type CreateMode } from './CreateAgentDialog';

const mocks = vi.hoisted(() => ({
    push: vi.fn(),
    refresh: vi.fn(),
    describe: vi.fn(),
    blank: vi.fn(),
    templates: vi.fn(),
    duplicate: vi.fn(),
    connections: vi.fn(),
    providerApps: vi.fn(),
    startOAuth: vi.fn(),
    activate: vi.fn(),
    canConnect: true,
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }) }));
vi.mock('@/lib/auth', () => ({
    useAuth: () => ({ user: { id: '1' }, getAccessToken: async () => 'token' }),
}));
vi.mock('@/context/OrgConfigContext', () => ({
    useOrgConfig: () => ({ can: () => mocks.canConnect }),
}));
vi.mock('@/client/sdk.gen', () => ({
    createWorkflowFromTemplateApiV1WorkflowCreateTemplatePost: mocks.describe,
    createWorkflowApiV1WorkflowCreateDefinitionPost: mocks.blank,
    getWorkflowTemplatesApiV1WorkflowTemplatesGet: mocks.templates,
    duplicateWorkflowTemplateApiV1WorkflowTemplatesDuplicatePost: mocks.duplicate,
    listConnectionsApiV1IntegrationsConnectionsGet: mocks.connections,
    listProviderAppsApiV1IntegrationsProviderAppsGet: mocks.providerApps,
    startOauthApiV1IntegrationsOauthStartPost: mocks.startOAuth,
    activateConnectionApiV1IntegrationsConnectionsConnectionIdActivatePost: mocks.activate,
}));

const RECEPTIONIST = {
    id: 3,
    template_name: 'AI Receptionist',
    template_description: 'Answers every call and takes messages.',
    template_json: {
        nodes: [{ type: 'startCall', data: { greeting: 'Hi, thanks for calling {{business_name}}.' } }],
    },
    setup_fields: [
        { key: 'business_name', label: 'Business name' },
        { key: 'website', label: 'Website', type: 'url', required: false },
    ],
    call_type: 'inbound',
    icon: 'phone',
    featured: true,
    integrations: ['google-calendar'],
    created_at: '',
};

const CALENDAR = {
    id: 'conn-1',
    provider: 'google-calendar',
    auth_mode: 'oauth2',
    account_label: 'desk@bloom.ie',
    status: 'active',
    tool_uuids: ['cal-tool'],
    created_at: '',
    updated_at: '',
};

beforeEach(() => {
    vi.clearAllMocks();
    vi.restoreAllMocks();
    mocks.canConnect = true;
    mocks.templates.mockResolvedValue({ data: [RECEPTIONIST] });
    mocks.connections.mockResolvedValue({ data: { connections: [] } });
    mocks.providerApps.mockResolvedValue({
        data: { provider_apps: [{ id: 'app-1', provider: 'google', managed: true }] },
    });
});

function renderDialog(initialMode?: CreateMode) {
    const onOpenChange = vi.fn();
    render(<CreateAgentDialog open onOpenChange={onOpenChange} initialMode={initialMode} />);
    return { onOpenChange };
}

async function openReceptionist() {
    fireEvent.click(await screen.findByRole('button', { name: /AI Receptionist/ }));
    return screen.findByRole('heading', { name: 'Set up your AI Receptionist' });
}

it('opens on the ready-made agents, featured first', async () => {
    renderDialog();

    expect(screen.getByRole('heading', { name: 'What should your agent do?' })).toBeTruthy();
    const card = await screen.findByRole('button', { name: /AI Receptionist/ });
    expect(card.textContent).toContain('Most popular');
    expect(card.textContent).toContain('Answers calls · Calendar · 2 min');
});

it('asks the template’s questions, previews the greeting, and creates the agent', async () => {
    mocks.duplicate.mockResolvedValue({ data: { id: 42 } });
    renderDialog();
    await openReceptionist();

    // A required answer is missing.
    fireEvent.click(screen.getByRole('button', { name: 'Create agent' }));
    expect(screen.getByText('Please add business name.')).toBeTruthy();
    expect(mocks.duplicate).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText('Business name'), { target: { value: ' Bloom Dental ' } });
    expect(screen.getByLabelText('Preview').textContent).toContain('Hi, thanks for calling Bloom Dental.');
    // No calendar yet: the agent takes a message instead.
    expect(await screen.findByRole('button', { name: 'Connect Google Calendar' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Create agent' }));

    expect(await screen.findByRole('heading', { name: 'Your agent is ready' })).toBeTruthy();
    expect(mocks.duplicate.mock.calls[0][0].body).toEqual({
        template_id: 3,
        workflow_name: 'AI Receptionist · Bloom Dental',
        values: { business_name: 'Bloom Dental', website: '' },
        integration_tools: {},
    });
    expect(screen.getByText('Takes a message for now')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Talk to your agent' }));
    expect(mocks.push).toHaveBeenCalledWith('/workflow/42?onboarding=web_call');
});

it('attaches the workspace’s Google Calendar when it is connected', async () => {
    mocks.connections.mockResolvedValue({ data: { connections: [CALENDAR] } });
    mocks.duplicate.mockResolvedValue({ data: { id: 7 } });
    renderDialog();
    await openReceptionist();

    expect(await screen.findByText('Google Calendar connected')).toBeTruthy();
    expect(screen.getByText(/desk@bloom\.ie/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Business name'), { target: { value: 'Bloom Dental' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create agent' }));

    expect(await screen.findByText('Books into Google Calendar')).toBeTruthy();
    expect(mocks.duplicate.mock.calls[0][0].body.integration_tools).toEqual({ 'google-calendar': 'cal-tool' });
});

it('connects Google Calendar in a pop-up without leaving the dialog', async () => {
    const popup = { location: { href: '' }, close: vi.fn() };
    vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window);
    vi.spyOn(window, 'close').mockImplementation(() => {});
    mocks.startOAuth.mockResolvedValue({
        data: { authorization_url: 'https://accounts.google.com/o/oauth2/auth?x=1', browser_nonce: 'nonce-1' },
    });
    mocks.activate.mockResolvedValue({ data: CALENDAR });
    renderDialog();
    await openReceptionist();
    fireEvent.change(screen.getByLabelText('Business name'), { target: { value: 'Bloom Dental' } });

    fireEvent.click(await screen.findByRole('button', { name: 'Connect Google Calendar' }));
    expect(await screen.findByText(/Finish signing in to Google/)).toBeTruthy();
    await waitFor(() => expect(popup.location.href).toContain('accounts.google.com'));
    expect(mocks.startOAuth.mock.calls[0][0].body).toEqual({
        provider: 'google-calendar',
        provider_app_id: 'app-1',
        optional_scopes: [],
    });

    // Google sends the pop-up back to /integrations, which hands over.
    window.history.replaceState(null, '', `/integrations?integration_result=success&connection_id=${'0b6f1f0e-1c1a-4d3e-9a55-5f6c7e8d9a0b'}&provider=google-calendar`);
    expect(handOffOAuthReturn()).toBe(true);
    window.history.replaceState(null, '', '/');

    expect(await screen.findByText('Google Calendar connected')).toBeTruthy();
    expect(mocks.activate.mock.calls[0][0]).toEqual({
        path: { connection_id: '0b6f1f0e-1c1a-4d3e-9a55-5f6c7e8d9a0b' },
        body: { browser_nonce: 'nonce-1' },
    });
    // The answer typed before connecting is still there.
    expect((screen.getByLabelText('Business name') as HTMLInputElement).value).toBe('Bloom Dental');
});

it('leaves the calendar off when the user unticks it', async () => {
    mocks.connections.mockResolvedValue({ data: { connections: [CALENDAR] } });
    mocks.duplicate.mockResolvedValue({ data: { id: 7 } });
    renderDialog();
    await openReceptionist();

    fireEvent.click(await screen.findByRole('checkbox'));
    fireEvent.change(screen.getByLabelText('Business name'), { target: { value: 'Bloom Dental' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create agent' }));

    await waitFor(() => expect(mocks.duplicate).toHaveBeenCalled());
    expect(mocks.duplicate.mock.calls[0][0].body.integration_tools).toEqual({});
});

it('sends a workspace with its own Google client to Integrations, and notices on return', async () => {
    mocks.providerApps.mockResolvedValue({ data: { provider_apps: [] } });
    renderDialog();
    await openReceptionist();

    const link = await screen.findByRole('link', { name: /Connect Google Calendar/ });
    expect(link.getAttribute('href')).toBe('/integrations');
    expect(link.getAttribute('target')).toBe('_blank');

    mocks.connections.mockResolvedValue({ data: { connections: [CALENDAR] } });
    fireEvent.focus(window);
    expect(await screen.findByText('Google Calendar connected')).toBeTruthy();
});

it('tells someone who can’t connect integrations to ask an admin', async () => {
    mocks.canConnect = false;
    renderDialog();
    await openReceptionist();

    expect(await screen.findByText(/Ask one to connect Google Calendar in Integrations/)).toBeTruthy();
    expect(screen.getByText('Admin only')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Connect Google Calendar/ })).toBeNull();
});

it('says so when calendar connections are off on this server', async () => {
    mocks.connections.mockResolvedValue({ error: { code: 'tools_service_not_configured', detail: 'Not configured' } });
    renderDialog();
    await openReceptionist();

    expect(await screen.findByText(/aren’t switched on for this server yet/)).toBeTruthy();
    expect(screen.getByText('Not available yet')).toBeTruthy();
});

it('shows the API error and stays on the questions', async () => {
    mocks.duplicate.mockResolvedValue({ error: { detail: 'Business name is required.' } });
    renderDialog();
    await openReceptionist();

    fireEvent.change(screen.getByLabelText('Business name'), { target: { value: 'Bloom' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create agent' }));

    expect((await screen.findByRole('alert')).textContent).toBe('Business name is required.');
    expect(screen.getByRole('heading', { name: 'Set up your AI Receptionist' })).toBeTruthy();
});

it('says so when there are no ready-made agents yet', async () => {
    mocks.templates.mockResolvedValue({ data: [] });
    renderDialog();

    expect(await screen.findByText(/Ready-made agents are on their way/)).toBeTruthy();
});

it('builds an agent from a description', async () => {
    mocks.describe.mockResolvedValue({ data: { id: 42 } });
    renderDialog();

    fireEvent.click(screen.getByRole('button', { name: 'Describe it in your own words →' }));
    const build = screen.getByRole('button', { name: 'Build my agent' });
    expect(build).toHaveProperty('disabled', true);

    fireEvent.click(screen.getByRole('radio', { name: /It makes calls/ }));
    fireEvent.change(screen.getByLabelText('What should it do?'), {
        target: { value: 'Call new leads from the website. Ask what they need and book a call.' },
    });
    fireEvent.click(build);

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith('/workflow/42?onboarding=web_call'));
    expect(mocks.describe.mock.calls[0][0].body).toEqual({
        call_type: 'outbound',
        use_case: 'Call new leads from the website.',
        activity_description: 'Call new leads from the website. Ask what they need and book a call.',
    });
});

it('fills the description from an example', () => {
    renderDialog('describe');

    fireEvent.click(screen.getByRole('button', { name: 'Ask customers for feedback' }));

    expect((screen.getByLabelText('What should it do?') as HTMLTextAreaElement).value).toMatch(/^Call customers/);
    expect(screen.getByRole('radio', { name: /It makes calls/ }).getAttribute('aria-checked')).toBe('true');
});

it('starts from scratch with a default name', async () => {
    mocks.blank.mockResolvedValue({ data: { id: 7 } });
    renderDialog();

    fireEvent.click(screen.getByRole('button', { name: 'Start from scratch' }));
    fireEvent.click(screen.getByRole('button', { name: 'Create and open' }));

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith('/workflow/7?onboarding=web_call'));
    expect(mocks.blank.mock.calls[0][0].body.name).toBe('Untitled agent');
});
