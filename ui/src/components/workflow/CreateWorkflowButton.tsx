'use client';

import { PlusIcon } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { type ComponentProps, useEffect } from 'react';

import { Button } from '@/components/ui/button';
import type { CreateMode } from '@/components/workflow/CreateAgentWizard';

const CREATE_PARAM = 'create';
const MODES: CreateMode[] = ['template', 'describe', 'blank'];

interface CreateWorkflowButtonProps {
    /**
     * When the URL carries `?create=<mode>` (old redirects / bookmarks), send
     * the user to the full-page wizard. Only one button on a page should set this.
     */
    openFromUrl?: boolean;
    /** `toolbar` in the app header's actions; the default size elsewhere. */
    size?: ComponentProps<typeof Button>['size'];
}

export function CreateWorkflowButton({ openFromUrl = false, size }: CreateWorkflowButtonProps) {
    const router = useRouter();
    const searchParams = useSearchParams();

    const requested = openFromUrl ? searchParams.get(CREATE_PARAM) : null;
    useEffect(() => {
        if (requested === null) return;
        const mode = MODES.includes(requested as CreateMode) ? (requested as CreateMode) : 'template';
        router.replace(`/workflow/create?mode=${mode}`);
    }, [requested, router]);

    return (
        <Button size={size} onClick={() => router.push('/workflow/create')}>
            <PlusIcon className="w-4 h-4" />
            Create agent
        </Button>
    );
}
