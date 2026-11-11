import { render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

import CreateWorkflowPage from './page';

const mocks = vi.hoisted(() => ({ query: '', wizard: vi.fn() }));
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams(mocks.query) }));
vi.mock('@/components/workflow/CreateAgentWizard', () => ({
    CreateAgentWizard: ({ initialMode }: { initialMode: string }) => {
        mocks.wizard(initialMode);
        return <p>wizard:{initialMode}</p>;
    },
}));

beforeEach(() => {
    mocks.wizard.mockClear();
});

it.each([
    ['', 'template'],
    ['mode=describe', 'describe'],
    ['mode=blank', 'blank'],
    // Old bookmarks and sign-in redirects used ?create=.
    ['create=describe', 'describe'],
    ['mode=blank&create=describe', 'blank'],
    ['mode=nonsense', 'template'],
])('?%s opens the wizard on %s', async (query, mode) => {
    mocks.query = query;
    render(<CreateWorkflowPage />);

    expect(await screen.findByText(`wizard:${mode}`)).toBeTruthy();
});
