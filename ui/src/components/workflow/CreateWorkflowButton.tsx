'use client';

import { PlusIcon } from 'lucide-react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { type ComponentProps, useEffect, useState } from 'react';

import { Button } from "@/components/ui/button";
import { CreateAgentDialog, type CreateMode } from '@/components/workflow/CreateAgentDialog';

const CREATE_PARAM = 'create';
const MODES: CreateMode[] = ['template', 'describe', 'blank'];

interface CreateWorkflowButtonProps {
    /**
     * Open the dialog when the URL carries `?create=<mode>` (where the old
     * /workflow/create page now redirects). Only one button on a page should
     * set this.
     */
    openFromUrl?: boolean;
    /** `toolbar` in the app header's actions; the default size elsewhere. */
    size?: ComponentProps<typeof Button>["size"];
}

export function CreateWorkflowButton({ openFromUrl = false, size }: CreateWorkflowButtonProps) {
    const router = useRouter();
    const pathname = usePathname();
    const searchParams = useSearchParams();
    const [open, setOpen] = useState(false);
    const [initialMode, setInitialMode] = useState<CreateMode>('template');

    const requested = openFromUrl ? searchParams.get(CREATE_PARAM) : null;
    useEffect(() => {
        if (requested === null) return;
        setInitialMode(MODES.includes(requested as CreateMode) ? (requested as CreateMode) : 'template');
        setOpen(true);
        // Drop the param so a refresh or Back doesn't reopen the dialog.
        const params = new URLSearchParams(searchParams.toString());
        params.delete(CREATE_PARAM);
        const query = params.toString();
        router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    }, [requested, pathname, router, searchParams]);

    return (
        <>
            <Button
                size={size}
                onClick={() => {
                    setInitialMode('template');
                    setOpen(true);
                }}
            >
                <PlusIcon className="w-4 h-4" />
                Create agent
            </Button>
            <CreateAgentDialog open={open} onOpenChange={setOpen} initialMode={initialMode} />
        </>
    );
}
