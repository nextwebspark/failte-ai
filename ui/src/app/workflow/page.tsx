import { Suspense } from 'react';

import { getWorkflowsApiV1WorkflowFetchGet, listFoldersApiV1FolderGet } from '@/client/sdk.gen';
import type { FolderResponse, WorkflowListResponse } from '@/client/types.gen';
import { Card, CardContent } from '@/components/ui/card';
import { SectionHeading } from '@/components/ui/section-heading';
import { Skeleton } from '@/components/ui/skeleton';
import { CreateWorkflowButton } from "@/components/workflow/CreateWorkflowButton";
import { AgentFolderView } from '@/components/workflow/folders/AgentFolderView';
import { CreateFolderButton } from '@/components/workflow/folders/CreateFolderButton';
import { FolderSection } from '@/components/workflow/folders/FolderSection';
import { UploadWorkflowButton } from '@/components/workflow/UploadWorkflowButton';
import { getServerAccessToken, getServerAuthProvider } from '@/lib/auth/server';
import logger from '@/lib/logger';

import WorkflowLayout from "./WorkflowLayout";

export const dynamic = 'force-dynamic';

// Server component for workflow list
async function WorkflowList() {
    const authProvider = await getServerAuthProvider();
    const accessToken = await getServerAccessToken();

    if (!accessToken) {
        // If no token, user needs to sign in
        const { redirect } = await import('next/navigation');
        if (authProvider === 'stack') {
            redirect('/');
        } else {
            // For OSS mode, this shouldn't happen as token is auto-generated
            return (
                <div className="font-mono text-sm text-danger">
                    Authentication required. Please refresh the page.
                </div>
            );
        }
    }

    try {
        // Fetch both active and archived workflows in a single request
        const response = await getWorkflowsApiV1WorkflowFetchGet({
            headers: {
                'Authorization': `Bearer ${accessToken}`,
            },
            query: {
                status: 'active,archived'
            }
        });

        const allWorkflowData = response.data ? (Array.isArray(response.data) ? response.data : [response.data]) : [];

        // Separate active and archived workflows
        const activeWorkflows = allWorkflowData
            .filter((w: WorkflowListResponse) => w.status === 'active')
            .sort((a: WorkflowListResponse, b: WorkflowListResponse) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

        const archivedWorkflows = allWorkflowData
            .filter((w: WorkflowListResponse) => w.status === 'archived')
            .sort((a: WorkflowListResponse, b: WorkflowListResponse) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

        // Fetch folders for grouping active agents. A failure here shouldn't
        // break the page — fall back to an empty list (flat, ungrouped view).
        let folders: FolderResponse[] = [];
        try {
            const foldersResponse = await listFoldersApiV1FolderGet({
                headers: {
                    'Authorization': `Bearer ${accessToken}`,
                },
            });
            folders = foldersResponse.data ?? [];
        } catch (folderErr) {
            logger.error(`Error fetching folders: ${folderErr}`);
        }

        return (
            <>
                {/* Active Workflows Section */}
                <div className="mb-8">
                    <SectionHeading>Active Agents</SectionHeading>
                    {activeWorkflows.length > 0 || folders.length > 0 ? (
                        <AgentFolderView workflows={activeWorkflows} folders={folders} />
                    ) : (
                        <div className="rounded-lg border border-dashed border-line bg-panel-2 p-8 text-center font-mono text-[12.5px] text-ink-3">
                            No active workflows found. Create your first workflow to get started.
                        </div>
                    )}
                </div>

                {/* Archived Section — collapsible, same design as the folder/Uncategorized sections */}
                {archivedWorkflows.length > 0 && (
                    <div className="mb-8">
                        <FolderSection kind="archived" workflows={archivedWorkflows} />
                    </div>
                )}
            </>
        );
    } catch (err) {
        logger.error(`Error fetching workflows: ${err}`);
        return (
            <div className="font-mono text-sm text-danger">
                Failed to load Workflows. Please Try Again Later.
            </div>
        );
    }
}

async function PageContent() {

    const workflowList = await WorkflowList();

    return (
        <div className="container mx-auto px-4 py-8">
            {/* Your Workflows Section */}
            <div className="mb-6">
                <div className="mb-6 flex items-center justify-between gap-4">
                    <h1 className="text-xl font-bold tracking-tight">Your Agents</h1>
                    <div className="flex gap-2">
                        <UploadWorkflowButton />
                        <CreateFolderButton />
                        <CreateWorkflowButton />
                    </div>
                </div>
                {workflowList}
            </div>
        </div>
    );
}

function WorkflowsLoading() {
    return (
        <div className="container mx-auto px-4 py-8">
            <div className="mb-6">
                <div className="mb-6 flex items-center justify-between gap-4">
                    <Skeleton className="h-7 w-48" />
                    <div className="flex gap-2">
                        <Skeleton className="h-9 w-28" />
                        <Skeleton className="h-9 w-32" />
                    </div>
                </div>
                <Skeleton className="mb-4 h-5 w-36" />
                <Card>
                    <CardContent className="p-0">
                        <Skeleton className="h-96 rounded-lg" />
                    </CardContent>
                </Card>
            </div>
        </div>
    );
}

export default function WorkflowPage() {
    return (
        <WorkflowLayout showFeaturesNav={true}>
            <Suspense fallback={<WorkflowsLoading />}>
                <PageContent />
            </Suspense>
        </WorkflowLayout>

    );
}
