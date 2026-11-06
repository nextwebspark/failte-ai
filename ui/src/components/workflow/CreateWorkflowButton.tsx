'use client';

import { PlusIcon } from 'lucide-react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { type ComponentProps, useEffect } from 'react';

import { Button } from '@/components/ui/button';
import type { CreateMode } from '@/components/workflow/CreateAgentWizard';
import { useOrgConfig } from '@/context/OrgConfigContext';

const CREATE_PARAM = 'create';
const MODES: CreateMode[] = ['template', 'describe', 'blank'];
export const CREATE_AGENT_HREF = '/workflow/create';

interface CreateWorkflowButtonProps {
    /**
     * When the URL carries `?create=<mode>` (old redirects / bookmarks), send
     * the user to the full-page wizard. Only one button on a page should set this.
     */
    openFromUrl?: boolean;
    /** `toolbar` in the app header's actions; the default size elsewhere. */
    size?: ComponentProps<typeof Button>['size'];
}

/** "Create agent", for roles that can change agents; nothing for the rest. */
export function CreateWorkflowButton({ openFromUrl = false, size }: CreateWorkflowButtonProps) {
    const router = useRouter();
    const searchParams = useSearchParams();
    const { can } = useOrgConfig();
    const canCreate = can('agents:write');

    const requested = openFromUrl && canCreate ? searchParams.get(CREATE_PARAM) : null;
    useEffect(() => {
        if (requested === null) return;
        const mode = MODES.includes(requested as CreateMode) ? (requested as CreateMode) : 'template';
        router.replace(`${CREATE_AGENT_HREF}?mode=${mode}`);
    }, [requested, router]);

    if (!canCreate) return null;

    return (
        <Button asChild size={size}>
            <Link href={CREATE_AGENT_HREF}>
                <PlusIcon className="w-4 h-4" aria-hidden />
                Create agent
            </Link>
        </Button>
    );
}
