import { AlertCircle, RotateCw } from 'lucide-react';
import Link from 'next/link';
import { Suspense } from 'react';

import { getWorkflowsApiV1WorkflowFetchGet, listFoldersApiV1FolderGet } from '@/client/sdk.gen';
import type { FolderResponse, WorkflowListResponse } from '@/client/types.gen';
import { PageActions } from '@/components/layout/PageActionsSlot';
import { Button } from '@/components/ui/button';
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
// works (and a leftover ?create= still routes to the full-page wizard).
function WorkflowListError() {
    return (
        <>
            <PageActions>
                <UploadWorkflowButton />
                <CreateWorkflowButton openFromUrl size="toolbar" />
            </PageActions>
            <ListMessage
                title={"We couldn't load your agents"}
                body="Please check your connection and try again."
            />
        </>
    );
}

// A calm "couldn't load" in the Calls page's shape. "Try again" is a plain
// link back to this page, so it works without any client script.
function ListMessage({ title, body }: { title: string; body: string }) {
    return (
        <div role="alert" className="flex flex-col items-center gap-2 rounded-xl border border-line bg-panel px-6 py-12 text-center">
            <span className="grid size-11 place-items-center rounded-full bg-danger-dim text-danger" aria-hidden>
                <AlertCircle className="size-5" />
            </span>
            <p className="font-semibold text-foreground">{title}</p>
            <p className="max-w-sm text-sm text-ink-3">{body}</p>
            <Button asChild variant="outline" className="mt-2 min-h-10">
                <Link href="/workflow" prefetch={false}>
                    <RotateCw className="size-4" aria-hidden />
                    Try again
                </Link>
            </Button>
        </div>
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
                <ListMessage
                    title="Please sign in again"
                    body="Your session has ended. Reloading the page will take you to sign in."
                />
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
