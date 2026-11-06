'use client';

import { useParams, usePathname, useRouter, useSearchParams } from 'next/navigation';
import posthog from 'posthog-js';
import { useEffect, useMemo, useState } from 'react';

import RenderWorkflow from '@/app/workflow/[workflowId]/RenderWorkflow';
import { getWorkflowApiV1WorkflowFetchWorkflowIdGet, getWorkflowVersionsApiV1WorkflowWorkflowIdVersionsGet } from '@/client/sdk.gen';
import type { WorkflowResponse, WorkflowVersionResponse } from '@/client/types.gen';
import { FlowEdge, FlowNode } from '@/components/flow/types';
import { PostHogEvent } from '@/constants/posthog-events';
import { UnsavedChangesProvider } from '@/context/UnsavedChangesContext';
import { useAuth } from '@/lib/auth';
import logger from '@/lib/logger';
import { WorkflowConfigurations } from '@/types/workflow-configurations';

import WorkflowLayout from '../WorkflowLayout';
import { SectionError } from './components/SectionStates';
import { ConversationSkeleton, SmallScreenDiagramNote, useIsSmallScreen } from './components/SmallScreenDiagramNote';

const LOAD_FAILED = "We couldn't load this agent";
const NOT_FOUND = "We couldn't find this agent";

export default function WorkflowDetailPage() {
    const params = useParams();
    const searchParams = useSearchParams();
    const router = useRouter();
    const pathname = usePathname();
    const workflowId = Number(params.workflowId);
    const version = searchParams.get('version');
    const requestKey = `${workflowId}:${version ?? 'current'}`;
    const [loaded, setLoaded] = useState<{
        key: string;
        workflow: WorkflowResponse;
        version?: WorkflowVersionResponse;
    }>();
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const { user, redirectToLogin, loading: authLoading } = useAuth();
    // Capture once so we still open the tester after stripping the param.
    const [openTesterOnLoad] = useState(() => searchParams.get('onboarding') === 'web_call');
    // Phones get a note instead of the diagram, unless the owner asks for it.
    const isSmallScreen = useIsSmallScreen();
    const [showDiagramAnyway, setShowDiagramAnyway] = useState(false);
    // Bumped by "Try again" to refetch.
    const [attempt, setAttempt] = useState(0);

    useEffect(() => {
        if (searchParams.get('onboarding') !== 'web_call') return;
        const next = new URLSearchParams(searchParams.toString());
        next.delete('onboarding');
        const query = next.toString();
        router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    }, [pathname, router, searchParams]);

    // Redirect if not authenticated
    useEffect(() => {
        if (!authLoading && !user) {
            redirectToLogin();
        }
    }, [authLoading, user, redirectToLogin]);

    useEffect(() => {
        if (authLoading || !user) return;
        let cancelled = false;
        setLoading(true);
        setError(null);
        const fetchWorkflow = async () => {
            try {
                if (version !== null && version !== 'latest' && (
                    !/^[1-9]\d*$/.test(version) || !Number.isSafeInteger(Number(version))
                )) {
                    setError('Invalid version. Use a version number or “latest”.');
                    return;
                }
                const [response, versionResponse] = await Promise.all([
                    getWorkflowApiV1WorkflowFetchWorkflowIdGet({
                        path: { workflow_id: workflowId },
                    }),
                    version === null ? Promise.resolve(null) : getWorkflowVersionsApiV1WorkflowWorkflowIdVersionsGet({
                        path: { workflow_id: workflowId },
                        query: version === 'latest'
                            ? { status: 'published', limit: 1 }
                            : { version_number: Number(version), limit: 1 },
                    }),
                ]);
                if (cancelled) return;

                if (response.error) {
                    setError(response.response?.status === 404 ? NOT_FOUND : LOAD_FAILED);
                    return;
                }

                const workflow = response.data;
                if (!workflow) {
                    setError(NOT_FOUND);
                    return;
                }
                if (versionResponse?.error) {
                    setError("We couldn't load this version");
                    return;
                }
                const selectedVersion = versionResponse?.data?.[0];
                if (version !== null && !selectedVersion) {
                    setError('Version not found');
                    return;
                }
                setLoaded({ key: requestKey, workflow, version: selectedVersion });
                posthog.capture(PostHogEvent.WORKFLOW_EDITOR_OPENED, {
                    workflow_id: workflow.id,
                    workflow_name: workflow.name,
                });
            } catch (err) {
                if (!cancelled) setError(LOAD_FAILED);
                logger.error(`Error fetching workflow: ${err}`);
            } finally {
                if (!cancelled) setLoading(false);
            }
        };

        void fetchWorkflow();
        return () => { cancelled = true; };
    }, [workflowId, version, requestKey, user, authLoading, attempt]);

    const stableUser = useMemo(() => user, [user]);
    const workflow = loaded?.key === requestKey ? loaded.workflow : undefined;
    const selectedVersion = loaded?.key === requestKey ? loaded.version : undefined;
    const definition = selectedVersion ? selectedVersion.workflow_json : workflow?.workflow_definition;
    const configurations = selectedVersion ? selectedVersion.workflow_configurations : workflow?.workflow_configurations;
    const templateVariables = selectedVersion ? selectedVersion.template_context_variables : workflow?.template_context_variables;

    if (authLoading || loading || (!error && loaded?.key !== requestKey) || isSmallScreen === null) {
        return (
            <WorkflowLayout>
                <ConversationSkeleton />
            </WorkflowLayout>
        );
    }
    else if (error || !workflow) {
        return (
            <WorkflowLayout showFeaturesNav={false}>
                <div className="page-body">
                    <SectionError
                        title={error || NOT_FOUND}
                        message={error === NOT_FOUND
                            ? 'It may have been deleted, or the link is wrong. Go back to All voice agents to pick another.'
                            : 'Please check your connection and try again.'}
                        onRetry={error === NOT_FOUND ? undefined : () => setAttempt((n) => n + 1)}
                    />
                </div>
            </WorkflowLayout>
        );
    }
    else if (isSmallScreen && !showDiagramAnyway) {
        return (
            <WorkflowLayout>
                <SmallScreenDiagramNote workflowId={workflowId} onShowAnyway={() => setShowDiagramAnyway(true)} />
            </WorkflowLayout>
        );
    }
    else {
        return stableUser ? (
            // Guards the nav: the section links are <a> tags, so an unsaved
            // graph now asks before the shell swaps the centre panel.
            <UnsavedChangesProvider>
            <RenderWorkflow
                key={requestKey}
                initialWorkflowName={workflow.name}
                workflowId={workflow.id}
                workflowUuid={workflow.workflow_uuid ?? undefined}
                openTesterOnLoad={openTesterOnLoad}
                initialFlow={{
                    nodes: definition?.nodes as FlowNode[],
                    edges: definition?.edges as FlowEdge[],
                    viewport: { x: 0, y: 0, zoom: 0 }
                }}
                initialSelectedVersion={selectedVersion}
                initialTemplateContextVariables={templateVariables as Record<string, string> || {}}
                initialWorkflowConfigurations={
                    configurations
                        ? (configurations as WorkflowConfigurations)
                        : undefined
                }
                initialVersionNumber={workflow.version_number ?? null}
                initialVersionStatus={workflow.version_status ?? null}
                user={stableUser}
            />
            </UnsavedChangesProvider>
        ) : null;
    }
}
