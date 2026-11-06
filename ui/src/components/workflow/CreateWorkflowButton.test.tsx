import { render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';

import { CreateWorkflowButton } from './CreateWorkflowButton';

const mocks = vi.hoisted(() => ({
    push: vi.fn(),
    replace: vi.fn(),
    query: '',
    can: vi.fn<(...permissions: string[]) => boolean>(() => true),
}));
vi.mock('next/navigation', () => ({
    useRouter: () => ({ push: mocks.push, replace: mocks.replace }),
    useSearchParams: () => new URLSearchParams(mocks.query),
}));
vi.mock('@/context/OrgConfigContext', () => ({
    useOrgConfig: () => ({ can: mocks.can }),
}));

beforeEach(() => {
    vi.clearAllMocks();
    mocks.query = '';
    mocks.can.mockImplementation(() => true);
});

it('is a real link to the full-page wizard', () => {
    render(<CreateWorkflowButton />);

    const link = screen.getByRole('link', { name: 'Create agent' });
    expect(link.getAttribute('href')).toBe('/workflow/create');
    // A link, so it opens in a new tab and works with the keyboard; no button inside.
    expect(link.querySelector('button')).toBeNull();
    expect(screen.queryByRole('button')).toBeNull();
});

it.each([
    ['owner', ['agents:read', 'calls:read', 'reports:read', 'bookings:manage']],
    ['staff', ['agents:read', 'calls:read', 'reports:read']],
])('is hidden from the %s, who cannot change agents', (_role, perms) => {
    mocks.can.mockImplementation((...required: string[]) => required.every((p) => perms.includes(p)));
    const { container } = render(<CreateWorkflowButton openFromUrl />);

    expect(container.innerHTML).toBe('');
    expect(screen.queryByRole('link', { name: 'Create agent' })).toBeNull();
});

it('does not forward ?create= for roles that cannot create agents', () => {
    mocks.can.mockImplementation(() => false);
    mocks.query = 'create=describe';
    render(<CreateWorkflowButton openFromUrl />);

    expect(mocks.replace).not.toHaveBeenCalled();
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
