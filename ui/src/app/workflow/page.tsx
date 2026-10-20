import { Suspense } from 'react';

import { getWorkflowsApiV1WorkflowFetchGet, listFoldersApiV1FolderGet } from '@/client/sdk.gen';
import type { FolderResponse, WorkflowListResponse } from '@/client/types.gen';
import { PageActions } from '@/components/layout/PageActionsSlot';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { AgentList } from '@/components/workflow/AgentList';
import { CreateWorkflowButton } from "@/components/workflow/CreateWorkflowButton";
import { UploadWorkflowButton } from '@/components/workflow/UploadWorkflowButton';
import { getServerAccessToken, getServerAuthProvider } from '@/lib/auth/server';
import logger from '@/lib/logger';

import WorkflowLayout from "./WorkflowLayout";

export const dynamic = 'force-dynamic';

// The list couldn't load: keep Create / Import in the header so the page still
// works (and the /workflow/create redirect's ?create= still opens the dialog).
function WorkflowListError() {
    return (
        <>
            <PageActions>
                <UploadWorkflowButton />
                <CreateWorkflowButton openFromUrl size="toolbar" />
            </PageActions>
            <div className="font-mono text-sm text-danger">
                Couldn&apos;t load your agents. Please try again later.
            </div>
        </>
    );
}

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
        // The client resolves 4xx/5xx instead of throwing. Without this check a
        // failed fetch reads as "no agents" and shows the first-run welcome page.
        if (response.error) {
            logger.error(`Error fetching workflows: ${JSON.stringify(response.error)}`);
            return <WorkflowListError />;
        }

        const allWorkflowData = response.data ? (Array.isArray(response.data) ? response.data : [response.data]) : [];

        // Separate active and archived workflows. AgentList owns the ordering.
        const activeWorkflows = allWorkflowData.filter((w: WorkflowListResponse) => w.status === 'active');
        const archivedWorkflows = allWorkflowData.filter((w: WorkflowListResponse) => w.status === 'archived');

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

        // AgentList also owns the header actions, so the empty-state check
        // that hides them lives in one place.
        return (
            <AgentList
                activeWorkflows={activeWorkflows}
                archivedWorkflows={archivedWorkflows}
                folders={folders}
            />
        );
    } catch (err) {
        logger.error(`Error fetching workflows: ${err}`);
        return <WorkflowListError />;
    }
}

async function PageContent() {

    const workflowList = await WorkflowList();

    return (
        <div className="page-body">
            {/* The screen name lives in the app header (AppTopBar); the canvas
                does not repeat it here, so the body opens straight on content
                and the actions ride the header (see AgentList). */}
            {workflowList}
        </div>
    );
}

function WorkflowsLoading() {
    return (
        <div className="page-body space-y-5">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                {[0, 1, 2, 3].map((i) => (
                    <Skeleton key={i} className="h-[76px] rounded-lg" />
                ))}
            </div>
            <Skeleton className="h-9 w-full max-w-[360px]" />
            <Card>
                <CardContent className="p-0">
                    <Skeleton className="h-96 rounded-lg" />
                </CardContent>
            </Card>
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
