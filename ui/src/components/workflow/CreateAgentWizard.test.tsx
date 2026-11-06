import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

import { handOffOAuthReturn } from '@/app/integrations/oauthPopup';

import { CreateAgentWizard, type CreateMode } from './CreateAgentWizard';

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
    redirectToLogin: vi.fn(),
    warning: vi.fn(),
    canConnect: true,
    user: { id: '1' } as { id: string } | null,
    authLoading: false,
}));
vi.mock('sonner', () => ({ toast: { warning: mocks.warning } }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: mocks.push, refresh: mocks.refresh }) }));
vi.mock('next/link', () => ({
    default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
        <a href={href} {...rest}>
            {children}
        </a>
    ),
}));
vi.mock('@/lib/auth', () => ({
    useAuth: () => ({
        user: mocks.user,
        loading: mocks.authLoading,
        redirectToLogin: mocks.redirectToLogin,
        getAccessToken: async () => 'token',
    }),
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
    category: 'general',
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
    mocks.user = { id: '1' };
    mocks.authLoading = false;
    mocks.templates.mockResolvedValue({ data: [RECEPTIONIST] });
    mocks.connections.mockResolvedValue({ data: { connections: [] } });
    mocks.providerApps.mockResolvedValue({
        data: { provider_apps: [{ id: 'app-1', provider: 'google', managed: true }] },
    });
});

function renderWizard(initialMode?: CreateMode) {
    render(<CreateAgentWizard initialMode={initialMode} />);
}

async function openReceptionist() {
    fireEvent.click(await screen.findByRole('button', { name: /AI Receptionist/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Use this template' }));
    return screen.findByRole('heading', { name: 'Personalise your AI Receptionist' });
}

it('opens on the ready-made agents, featured first', async () => {
    renderWizard();

    expect(screen.getByRole('heading', { name: 'What should your agent do?' })).toBeTruthy();
    expect(screen.getByText('Choose template')).toBeTruthy();
    const card = await screen.findByRole('button', { name: /AI Receptionist/ });
    expect(card.textContent).toContain('Most popular');
    expect(card.textContent).toContain('Answers calls · Calendar · 2 min');
});

it('asks the template’s questions, previews the greeting, and creates the agent', async () => {
    mocks.duplicate.mockResolvedValue({ data: { id: 42 } });
    renderWizard();
    await openReceptionist();

    fireEvent.click(screen.getByRole('button', { name: 'Create agent' }));
    expect(screen.getByText('Please add business name.')).toBeTruthy();
    expect(mocks.duplicate).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText('Business name'), { target: { value: ' Bloom Dental ' } });
    expect(screen.getByLabelText('Preview').textContent).toContain('Hi, thanks for calling Bloom Dental.');
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
    expect(mocks.push).toHaveBeenCalledWith('/workflow/42/home?onboarding=web_call');
});

it('attaches the workspace’s Google Calendar when it is connected', async () => {
    mocks.connections.mockResolvedValue({ data: { connections: [CALENDAR] } });
    mocks.duplicate.mockResolvedValue({ data: { id: 7 } });
    renderWizard();
    await openReceptionist();

    expect(await screen.findByText('Google Calendar connected')).toBeTruthy();
    expect(screen.getByText(/desk@bloom\.ie/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Business name'), { target: { value: 'Bloom Dental' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create agent' }));

    expect(await screen.findByText('Books into Google Calendar')).toBeTruthy();
    expect(mocks.duplicate.mock.calls[0][0].body.integration_tools).toEqual({ 'google-calendar': 'cal-tool' });
});

it('connects Google Calendar in a pop-up without leaving the wizard', async () => {
    const popup = { location: { href: '' }, close: vi.fn() };
    vi.spyOn(window, 'open').mockReturnValue(popup as unknown as Window);
    vi.spyOn(window, 'close').mockImplementation(() => {});
    mocks.startOAuth.mockResolvedValue({
        data: { authorization_url: 'https://accounts.google.com/o/oauth2/auth?x=1', browser_nonce: 'nonce-1' },
    });
    mocks.activate.mockResolvedValue({ data: CALENDAR });
    renderWizard();
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

    window.history.replaceState(
        null,
        '',
        `/integrations?integration_result=success&connection_id=${'0b6f1f0e-1c1a-4d3e-9a55-5f6c7e8d9a0b'}&provider=google-calendar`,
    );
    expect(handOffOAuthReturn()).toBe(true);
    window.history.replaceState(null, '', '/');

    expect(await screen.findByText('Google Calendar connected')).toBeTruthy();
    expect(mocks.activate.mock.calls[0][0]).toEqual({
        path: { connection_id: '0b6f1f0e-1c1a-4d3e-9a55-5f6c7e8d9a0b' },
        body: { browser_nonce: 'nonce-1' },
    });
    expect((screen.getByLabelText('Business name') as HTMLInputElement).value).toBe('Bloom Dental');
});

it('leaves the calendar off when the user unticks it', async () => {
    mocks.connections.mockResolvedValue({ data: { connections: [CALENDAR] } });
    mocks.duplicate.mockResolvedValue({ data: { id: 7 } });
    renderWizard();
    await openReceptionist();

    fireEvent.click(await screen.findByRole('checkbox'));
    fireEvent.change(screen.getByLabelText('Business name'), { target: { value: 'Bloom Dental' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create agent' }));

    await waitFor(() => expect(mocks.duplicate).toHaveBeenCalled());
    expect(mocks.duplicate.mock.calls[0][0].body.integration_tools).toEqual({});
});

it('sends a workspace with its own Google client to Integrations, and notices on return', async () => {
    mocks.providerApps.mockResolvedValue({ data: { provider_apps: [] } });
    renderWizard();
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
    renderWizard();
    await openReceptionist();

    expect(await screen.findByText(/Ask one to connect Google Calendar in Integrations/)).toBeTruthy();
    expect(screen.getByText('Admin only')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Connect Google Calendar/ })).toBeNull();
});

it('says so when calendar connections are off on this server', async () => {
    mocks.connections.mockResolvedValue({ error: { code: 'tools_service_not_configured', detail: 'Not configured' } });
    renderWizard();
    await openReceptionist();

    expect(await screen.findByText(/aren’t switched on for this server yet/)).toBeTruthy();
    expect(screen.getByText('Not available yet')).toBeTruthy();
});

it('shows the API error and stays on the questions', async () => {
    mocks.duplicate.mockResolvedValue({ error: { detail: 'Business name is required.' } });
    renderWizard();
    await openReceptionist();

    fireEvent.change(screen.getByLabelText('Business name'), { target: { value: 'Bloom' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create agent' }));

    expect((await screen.findByRole('alert')).textContent).toBe('Business name is required.');
    expect(screen.getByRole('heading', { name: 'Personalise your AI Receptionist' })).toBeTruthy();
});

it('says so when there are no ready-made agents yet', async () => {
    mocks.templates.mockResolvedValue({ data: [] });
    renderWizard();

    expect(await screen.findByText(/Ready-made agents are on their way/)).toBeTruthy();
});

it('builds an agent from a description', async () => {
    mocks.describe.mockResolvedValue({ data: { id: 42 } });
    renderWizard();

    fireEvent.click(screen.getByRole('button', { name: 'Describe it in your own words →' }));
    const build = screen.getByRole('button', { name: 'Build my agent' });
    expect(build).toHaveProperty('disabled', true);

    fireEvent.click(screen.getByRole('radio', { name: /It makes calls/ }));
    fireEvent.change(screen.getByLabelText('What should it do?'), {
        target: { value: 'Call new leads from the website. Ask what they need and book a call.' },
    });
    fireEvent.click(build);

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith('/workflow/42/home?onboarding=web_call'));
    expect(mocks.describe.mock.calls[0][0].body).toEqual({
        call_type: 'outbound',
        use_case: 'Call new leads from the website.',
        activity_description: 'Call new leads from the website. Ask what they need and book a call.',
    });
});

it('fills the description from an example', () => {
    renderWizard('describe');

    fireEvent.click(screen.getByRole('button', { name: 'Ask customers for feedback' }));

    expect((screen.getByLabelText('What should it do?') as HTMLTextAreaElement).value).toMatch(/^Call customers/);
    expect(screen.getByRole('radio', { name: /It makes calls/ }).getAttribute('aria-checked')).toBe('true');
});

it('starts from scratch with a default name', async () => {
    mocks.blank.mockResolvedValue({ data: { id: 7 } });
    renderWizard();

    fireEvent.click(screen.getByRole('button', { name: 'Start from scratch' }));
    fireEvent.click(screen.getByRole('button', { name: 'Create and open' }));

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith('/workflow/7?onboarding=web_call'));
    expect(mocks.blank.mock.calls[0][0].body.name).toBe('Untitled agent');
});

const CLINIC = {
    ...RECEPTIONIST,
    id: 5,
    template_name: 'Clinic receptionist',
    template_description: 'Books clinic visits.',
    template_json: {
        nodes: [
            { type: 'startCall', data: { name: 'Help the patient', greeting: 'Hello, {{business_name}}.' } },
            { type: 'agentNode', data: { name: 'Take a message' } },
            { type: 'endCall', data: { name: 'End Call' } },
        ],
    },
    featured: false,
    category: 'clinic',
};

const REMINDER = {
    ...RECEPTIONIST,
    id: 9,
    template_name: 'Appointment reminder',
    template_description: 'Calls ahead of a visit.',
    call_type: 'outbound',
    featured: false,
    category: 'telephony',
    integrations: [],
};

it('sends a signed-out visitor to sign in instead of loading templates', async () => {
    mocks.user = null;
    renderWizard();

    await waitFor(() => expect(mocks.redirectToLogin).toHaveBeenCalled());
    expect(mocks.templates).not.toHaveBeenCalled();
});

it('waits for sign-in to finish before deciding', () => {
    mocks.user = null;
    mocks.authLoading = true;
    renderWizard();

    expect(mocks.redirectToLogin).not.toHaveBeenCalled();
});

it('says when the templates could not load, and tries again', async () => {
    mocks.templates.mockResolvedValueOnce({ error: { detail: 'Server error' } });
    renderWizard();

    expect((await screen.findByRole('alert')).textContent).toContain('Couldn’t load the ready-made agents');
    expect(screen.queryByText(/Ready-made agents are on their way/)).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('button', { name: /AI Receptionist/ })).toBeTruthy();
    expect(mocks.templates).toHaveBeenCalledTimes(2);
});

it('treats a network failure like a load error', async () => {
    mocks.templates.mockRejectedValueOnce(new Error('offline'));
    renderWizard();

    expect(await screen.findByRole('button', { name: 'Try again' })).toBeTruthy();
});

it('previews the featured template first, then whichever card is picked', async () => {
    mocks.templates.mockResolvedValue({ data: [CLINIC, RECEPTIONIST] });
    renderWizard();

    const preview = await screen.findByRole('complementary', { name: 'Template preview' });
    await waitFor(() => expect(preview.textContent).toContain('AI Receptionist'));

    fireEvent.click(screen.getByRole('button', { name: /Clinic receptionist/ }));
    expect(preview.textContent).toContain('Clinics');
    expect(preview.textContent).toContain('Help the patient');
    // End nodes are not steps the caller hears.
    expect(preview.textContent).not.toContain('End Call');
    expect(preview.textContent).toContain('Hello, [business_name].');
});

it('filters by industry and keeps the preview on a visible card', async () => {
    mocks.templates.mockResolvedValue({ data: [RECEPTIONIST, CLINIC, REMINDER] });
    renderWizard();
    await screen.findByRole('button', { name: /AI Receptionist/ });

    fireEvent.click(screen.getByRole('button', { name: 'Clinics' }));

    expect(screen.queryByRole('button', { name: /AI Receptionist/ })).toBeNull();
    const preview = screen.getByRole('complementary', { name: 'Template preview' });
    expect(preview.textContent).toContain('Clinic receptionist');
    fireEvent.click(screen.getByRole('button', { name: 'Use this template' }));
    expect(await screen.findByRole('heading', { name: 'Personalise your Clinic receptionist' })).toBeTruthy();
});

it('says so when no template matches both filters', async () => {
    mocks.templates.mockResolvedValue({ data: [RECEPTIONIST, CLINIC, REMINDER] });
    renderWizard();
    await screen.findByRole('button', { name: /AI Receptionist/ });

    fireEvent.click(screen.getByRole('button', { name: 'Clinics' }));
    fireEvent.click(screen.getByRole('button', { name: 'Call my customers' }));

    expect(screen.getByText(/No agents match these filters/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Use this template' })).toBeNull();
});

it('moves focus to each step’s heading', async () => {
    mocks.duplicate.mockResolvedValue({ data: { id: 42 } });
    renderWizard();
    // Focus moves in an effect that can run after the heading is in the DOM.
    const heading = await openReceptionist();
    await waitFor(() => expect(document.activeElement).toBe(heading));

    fireEvent.change(screen.getByLabelText('Business name'), { target: { value: 'Bloom' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create agent' }));
    const ready = await screen.findByRole('heading', { name: 'Your agent is ready', level: 1 });
    await waitFor(() => expect(document.activeElement).toBe(ready));
});

it('leaves focus alone on first load', async () => {
    renderWizard();
    await screen.findByRole('button', { name: /AI Receptionist/ });

    expect(document.activeElement).toBe(document.body);
});

it('goes back to the gallery from the questions, keeping the choice', async () => {
    renderWizard();
    await openReceptionist();

    fireEvent.click(screen.getByRole('button', { name: 'Back' }));

    expect(screen.getByRole('heading', { name: 'What should your agent do?' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /AI Receptionist/ }).getAttribute('aria-pressed')).toBe('true');
});

it('opens straight on a side path from the URL mode', () => {
    renderWizard('blank');

    expect(screen.getByRole('heading', { name: 'Start from scratch' })).toBeTruthy();
    expect(screen.queryByText('Choose template')).toBeNull();
});

it('lets the owner switch booking questions on and off, without typing', async () => {
    mocks.templates.mockResolvedValue({
        data: [
            {
                ...RECEPTIONIST,
                template_name: 'Restaurant bookings',
                featured: false,
                setup_fields: [
                    { key: 'business_name', label: 'Business name' },
                    {
                        key: 'booking_questions',
                        label: 'When someone books, also ask',
                        type: 'toggles',
                        required: false,
                        help: 'Day, time, name and phone number are always asked.',
                        options: [
                            { value: 'party_size', label: 'Party size', prompt: 'how many people', default: true },
                            { value: 'allergies', label: 'Allergies', prompt: 'about allergies', default: true },
                            { value: 'high_chair', label: 'High chair', prompt: 'about a high chair' },
                        ],
                    },
                ],
            },
        ],
    });
    mocks.duplicate.mockResolvedValue({ data: { id: 7 } });
    renderWizard();
    fireEvent.click(await screen.findByRole('button', { name: /Restaurant bookings/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Use this template' }));
    await screen.findByRole('heading', { name: 'Personalise your Restaurant bookings' });

    const group = screen.getByRole('group', { name: 'When someone books, also ask' });
    const toggle = (name: string) => screen.getByRole('button', { name });
    expect(toggle('Party size').getAttribute('aria-pressed')).toBe('true');
    expect(toggle('High chair').getAttribute('aria-pressed')).toBe('false');
    expect(group.getAttribute('aria-describedby')).toBeTruthy();
    expect(screen.getByText('Day, time, name and phone number are always asked.')).toBeTruthy();

    fireEvent.click(toggle('High chair'));
    fireEvent.click(toggle('Allergies'));
    expect(toggle('High chair').getAttribute('aria-pressed')).toBe('true');
    expect(toggle('Allergies').getAttribute('aria-pressed')).toBe('false');

    fireEvent.change(screen.getByLabelText('Business name'), { target: { value: 'Harbour Kitchen' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create agent' }));

    await screen.findByRole('heading', { name: 'Your agent is ready' });
    expect(mocks.duplicate.mock.calls[0][0].body.values).toEqual({
        business_name: 'Harbour Kitchen',
        booking_questions: 'party_size,high_chair',
    });
});

// -- appointment hours (from PR #147, on the wizard) -------------------------------

const RECEPTIONIST_WITH_HOURS = {
    ...RECEPTIONIST,
    setup_fields: [
        ...RECEPTIONIST.setup_fields,
        { key: 'appointment_hours', label: 'Appointment hours', type: 'appointment_hours', required: false },
    ],
};

/** A calendar other agents already book with, in hours set on Bookings. */
const BOOKING_CALENDAR = {
    ...CALENDAR,
    config: {
        calendar_id: 'primary',
        service_periods: [{ days: [1, 2, 3], first_start: '10:00', last_start: '15:15' }],
        slot_minutes: 45,
        timezone: 'America/New_York',
    },
};
const BOOKING_HOURS = {
    booking_days: [1, 2, 3],
    open_hour: 10,
    close_hour: 16,
    slot_minutes: 45,
    timezone: 'America/New_York',
};

function select(label: string): HTMLSelectElement {
    return screen.getByLabelText(label) as HTMLSelectElement;
}

async function openWithHours(connections: unknown[] = []) {
    mocks.templates.mockResolvedValue({ data: [RECEPTIONIST_WITH_HOURS] });
    mocks.connections.mockResolvedValue({ data: { connections } });
    renderWizard();
    await openReceptionist();
}

async function fillAndCreate() {
    fireEvent.change(screen.getByLabelText('Business name'), { target: { value: 'Bloom Dental' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create agent' }));
}

it('asks for appointment hours only when the agent books into a calendar', async () => {
    mocks.duplicate.mockResolvedValue({ data: { id: 42 } });
    await openWithHours();

    expect(await screen.findByRole('button', { name: 'Connect Google Calendar' })).toBeTruthy();
    expect(screen.queryByRole('group', { name: 'Appointment hours' })).toBeNull();
    await fillAndCreate();

    await waitFor(() => expect(mocks.duplicate).toHaveBeenCalled());
    const body = mocks.duplicate.mock.calls[0][0].body;
    expect(body).not.toHaveProperty('appointment_hours');
    expect(body).not.toHaveProperty('apply_to_calendar');
    expect(body.values).not.toHaveProperty('appointment_hours');
});

it('shows the hours a reused calendar books in (its service period) and leaves them alone', async () => {
    mocks.duplicate.mockResolvedValue({ data: { id: 7, calendar_hours: null } });
    await openWithHours([BOOKING_CALENDAR]);

    expect(await screen.findByRole('group', { name: 'Appointment hours' })).toBeTruthy();
    await waitFor(() => expect(select('From').value).toBe('10'));
    // Last start 15:15 plus a 45-minute appointment: open until 16:00.
    expect(select('To').value).toBe('16');
    expect(select('Appointment length').value).toBe('45');
    expect(select('Time zone').value).toBe('America/New_York');
    expect(screen.getByText(/every agent in this workspace that books with it/)).toBeTruthy();
    await fillAndCreate();

    expect(await screen.findByRole('heading', { name: 'Your agent is ready' })).toBeTruthy();
    const body = mocks.duplicate.mock.calls[0][0].body;
    expect(body.appointment_hours).toEqual(BOOKING_HOURS);
    expect(body.apply_to_calendar).toBe(false);
});

it('saves edited hours to a reused calendar', async () => {
    mocks.duplicate.mockResolvedValue({ data: { id: 7, calendar_hours: 'updated' } });
    await openWithHours([BOOKING_CALENDAR]);
    await waitFor(() => expect(select('From').value).toBe('10'));

    fireEvent.change(select('From'), { target: { value: '8' } });
    // Switching the calendar off and on again doesn't bring its hours back.
    fireEvent.click(screen.getByRole('checkbox'));
    expect(screen.queryByRole('group', { name: 'Appointment hours' })).toBeNull();
    fireEvent.click(screen.getByRole('checkbox'));
    expect(select('From').value).toBe('8');
    await fillAndCreate();

    expect(await screen.findByText('Books only in your appointment hours')).toBeTruthy();
    const body = mocks.duplicate.mock.calls[0][0].body;
    expect(body.appointment_hours).toEqual({ ...BOOKING_HOURS, open_hour: 8 });
    expect(body.apply_to_calendar).toBe(true);
});

it('keeps opening times that are not one window, and sends no hours', async () => {
    const lunchAndDinner = {
        ...CALENDAR,
        config: {
            calendar_id: 'primary',
            service_periods: [
                { days: [3, 4, 5], first_start: '12:00', last_start: '14:00' },
                { days: [3, 4, 5], first_start: '17:00', last_start: '21:00' },
            ],
        },
    };
    mocks.duplicate.mockResolvedValue({ data: { id: 7, calendar_hours: null } });
    await openWithHours([lunchAndDinner]);

    const group = await screen.findByRole('group', { name: 'Appointment hours' });
    expect(group.textContent).toContain('Thu–Sat, first booking 12:00, last 14:00');
    expect(group.textContent).toContain('Thu–Sat, first booking 17:00, last 21:00');
    expect(group.textContent).toContain('set on the Bookings page');
    expect(screen.queryByLabelText('From')).toBeNull();
    await fillAndCreate();

    await waitFor(() => expect(mocks.duplicate).toHaveBeenCalled());
    const body = mocks.duplicate.mock.calls[0][0].body;
    expect(body).not.toHaveProperty('appointment_hours');
    expect(body).not.toHaveProperty('apply_to_calendar');
});

it('treats a calendar with no booking hours saved as new', async () => {
    mocks.duplicate.mockResolvedValue({ data: { id: 7, calendar_hours: 'updated' } });
    await openWithHours([{ ...CALENDAR, config: { calendar_id: 'primary' } }]);

    expect(await screen.findByText(/These become the booking hours of your Google Calendar connection/)).toBeTruthy();
    await fillAndCreate();

    await waitFor(() => expect(mocks.duplicate).toHaveBeenCalled());
    const body = mocks.duplicate.mock.calls[0][0].body;
    expect(body.appointment_hours).toEqual({
        booking_days: [0, 1, 2, 3, 4],
        open_hour: 9,
        close_hour: 17,
        slot_minutes: 30,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    });
    expect(body.apply_to_calendar).toBe(true);
});

it('shows, but doesn’t let change, hours this role may not change', async () => {
    mocks.canConnect = false;
    await openWithHours([BOOKING_CALENDAR]);

    await waitFor(() => expect(select('From').value).toBe('10'));
    expect(select('From').disabled).toBe(true);
    expect(screen.getByRole('button', { name: 'Monday' })).toHaveProperty('disabled', true);
    expect(screen.getByText(/Only a workspace owner or admin can change them/)).toBeTruthy();
});

it.each([
    ['updated', 'Books only in your appointment hours', false],
    ['not_allowed', 'An owner or admin sets them on Bookings', false],
    ['failed', 'Not saved: set them on Bookings', true],
])('reports calendar hours that were %s', async (status, text, warns) => {
    mocks.duplicate.mockResolvedValue({ data: { id: 7, calendar_hours: status } });
    await openWithHours([BOOKING_CALENDAR]);
    await waitFor(() => expect(select('From').value).toBe('10'));

    fireEvent.change(select('To'), { target: { value: '18' } });
    await fillAndCreate();

    expect(await screen.findByText(text)).toBeTruthy();
    expect(mocks.warning).toHaveBeenCalledTimes(warns ? 1 : 0);
});

it('points at the hours when they make no sense', async () => {
    await openWithHours([BOOKING_CALENDAR]);
    await waitFor(() => expect(select('From').value).toBe('10'));

    fireEvent.change(select('From'), { target: { value: '17' } });
    await fillAndCreate();

    expect(screen.getByText('The closing time must be after the opening time.')).toBeTruthy();
    expect(document.activeElement).toBe(select('From'));
    expect(mocks.duplicate).not.toHaveBeenCalled();
});
