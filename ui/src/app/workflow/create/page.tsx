'use client';

import { useSearchParams } from 'next/navigation';
import { Suspense } from 'react';

import SpinLoader from '@/components/SpinLoader';
import { CreateAgentWizard, type CreateMode } from '@/components/workflow/CreateAgentWizard';

import WorkflowLayout from '../WorkflowLayout';

const MODES: CreateMode[] = ['template', 'describe', 'blank'];

function CreateWizardFromUrl() {
    const searchParams = useSearchParams();
    const raw = searchParams.get('mode') ?? searchParams.get('create');
    const initialMode: CreateMode =
        raw && MODES.includes(raw as CreateMode) ? (raw as CreateMode) : 'template';
    return <CreateAgentWizard initialMode={initialMode} />;
}

/**
 * Full-page Create agent wizard. Deep links:
 * `/workflow/create?mode=template|describe|blank` (also accepts legacy `?create=`).
 */
export default function CreateWorkflowPage() {
    return (
        <WorkflowLayout showFeaturesNav={false}>
            <Suspense fallback={<SpinLoader />}>
                <CreateWizardFromUrl />
            </Suspense>
        </WorkflowLayout>
    );
}
