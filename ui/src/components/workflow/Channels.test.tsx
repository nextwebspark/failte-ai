import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

const { Channels } = await import('./WorkflowTable');

describe('Channels', () => {
    it('shows an icon per way callers reach the agent', () => {
        render(<Channels channels={['web', 'phone']} />);
        const icons = screen.getAllByRole('img').map((icon) => icon.getAttribute('aria-label'));
        expect(icons).toEqual(['Phone', 'Website widget']);
    });

    it('says when nothing is connected', () => {
        render(<Channels channels={[]} />);
        expect(screen.getByText('Not connected')).toBeTruthy();
        render(<Channels channels={null} />);
        expect(screen.getAllByText('Not connected')).toHaveLength(2);
    });
});
