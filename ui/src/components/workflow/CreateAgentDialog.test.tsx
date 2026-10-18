import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

import { CreateAgentDialog } from './CreateAgentDialog';

const mocks = vi.hoisted(() => ({
    push: vi.fn(),
    describe: vi.fn(),
    blank: vi.fn(),
    templates: vi.fn(),
    duplicate: vi.fn(),
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock('@/lib/auth', () => ({
    useAuth: () => ({ user: { id: '1' }, getAccessToken: async () => 'token' }),
}));
vi.mock('@/client/sdk.gen', () => ({
    createWorkflowFromTemplateApiV1WorkflowCreateTemplatePost: mocks.describe,
    createWorkflowApiV1WorkflowCreateDefinitionPost: mocks.blank,
    getWorkflowTemplatesApiV1WorkflowTemplatesGet: mocks.templates,
    duplicateWorkflowTemplateApiV1WorkflowTemplatesDuplicatePost: mocks.duplicate,
}));

beforeEach(() => {
    vi.clearAllMocks();
});

function renderDialog(initialMode?: 'describe' | 'template' | 'blank') {
    const onOpenChange = vi.fn();
    render(<CreateAgentDialog open onOpenChange={onOpenChange} initialMode={initialMode} />);
    return { onOpenChange };
}

it('drafts an agent from a description and opens it with the test panel', async () => {
    mocks.describe.mockResolvedValue({ data: { id: 42 } });
    renderDialog();

    const create = screen.getByRole('button', { name: 'Create and open' });
    expect(create).toHaveProperty('disabled', true);

    fireEvent.click(screen.getByRole('radio', { name: 'Outbound' }));
    fireEvent.change(screen.getByLabelText('What kind of agent is it?'), { target: { value: ' Lead qualification ' } });
    fireEvent.change(screen.getByLabelText('What should it do?'), { target: { value: 'Call new leads.' } });
    fireEvent.click(create);

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith('/workflow/42?onboarding=web_call'));
    expect(mocks.describe.mock.calls[0][0].body).toEqual({
        call_type: 'outbound',
        use_case: 'Lead qualification',
        activity_description: 'Call new leads.',
    });
});

it('shows the API error and stays open when drafting fails', async () => {
    mocks.describe.mockResolvedValue({ error: { detail: 'Too many agents generated; please try again later.' } });
    renderDialog();

    fireEvent.change(screen.getByLabelText('What kind of agent is it?'), { target: { value: 'Reception' } });
    fireEvent.change(screen.getByLabelText('What should it do?'), { target: { value: 'Answer calls.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create and open' }));

    expect((await screen.findByRole('alert')).textContent).toBe('Too many agents generated; please try again later.');
    expect(mocks.push).not.toHaveBeenCalled();
});

it('creates a blank agent, defaulting the name', async () => {
    mocks.blank.mockResolvedValue({ data: { id: 7 } });
    renderDialog('blank');

    fireEvent.click(screen.getByRole('button', { name: 'Create and open' }));

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith('/workflow/7?onboarding=web_call'));
    expect(mocks.blank.mock.calls[0][0].body.name).toBe('Untitled agent');
});

it('copies the chosen template under its own name', async () => {
    mocks.templates.mockResolvedValue({
        data: [{ id: 3, template_name: 'Reception', template_description: 'Answers calls', template_json: {}, created_at: '' }],
    });
    mocks.duplicate.mockResolvedValue({ data: { id: 9 } });
    renderDialog('template');

    fireEvent.click(await screen.findByRole('radio', { name: /Reception/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Create and open' }));

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith('/workflow/9?onboarding=web_call'));
    expect(mocks.duplicate.mock.calls[0][0].body).toEqual({ template_id: 3, workflow_name: 'Reception' });
});

it('says so when there are no templates', async () => {
    mocks.templates.mockResolvedValue({ data: [] });
    renderDialog('template');

    expect(await screen.findByText(/No templates yet/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Create and open' })).toHaveProperty('disabled', true);
});
