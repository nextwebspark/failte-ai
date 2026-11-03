import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

import { CreateWorkflowButton } from './CreateWorkflowButton';

const mocks = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), query: '' }));
vi.mock('next/navigation', () => ({
    useRouter: () => ({ push: mocks.push, replace: mocks.replace }),
    useSearchParams: () => new URLSearchParams(mocks.query),
}));

beforeEach(() => {
    vi.clearAllMocks();
    mocks.query = '';
});

it('opens the full-page wizard', () => {
    render(<CreateWorkflowButton />);

    fireEvent.click(screen.getByRole('button', { name: 'Create agent' }));

    expect(mocks.push).toHaveBeenCalledWith('/workflow/create');
});

it.each([
    ['create=describe', '/workflow/create?mode=describe'],
    ['create=template', '/workflow/create?mode=template'],
    ['create=whatever', '/workflow/create?mode=template'],
])('forwards a leftover ?%s to the wizard', (query, target) => {
    mocks.query = query;
    render(<CreateWorkflowButton openFromUrl />);

    expect(mocks.replace).toHaveBeenCalledWith(target);
});

it('ignores ?create= unless it is the page’s chosen button', () => {
    mocks.query = 'create=describe';
    render(<CreateWorkflowButton />);

    expect(mocks.replace).not.toHaveBeenCalled();
});
