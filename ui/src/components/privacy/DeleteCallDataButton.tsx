'use client';

import { Loader2, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { deleteWorkflowRunDataApiV1WorkflowWorkflowIdRunsRunIdDelete } from '@/client/sdk.gen';
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Button, buttonVariants } from '@/components/ui/button';
import { detailFromError } from '@/lib/apiError';

interface DeleteCallDataButtonProps {
    workflowId: number;
    runId: number;
    /** Called once the call's data is gone, e.g. to reload the run. */
    onDeleted?: () => void;
}

/** Erases one call's recordings, transcript and caller details (a caller's
 *  erasure request). The call stays in usage history for billing. */
export function DeleteCallDataButton({ workflowId, runId, onDeleted }: DeleteCallDataButtonProps) {
    const [open, setOpen] = useState(false);
    const [deleting, setDeleting] = useState(false);

    const handleDelete = async () => {
        setDeleting(true);
        try {
            const response = await deleteWorkflowRunDataApiV1WorkflowWorkflowIdRunsRunIdDelete({
                path: { workflow_id: workflowId, run_id: runId },
            });
            if (response.error) {
                toast.error(detailFromError(response.error, 'Could not delete the call data'));
                return;
            }
            toast.success('Call data deleted');
            setOpen(false);
            onDeleted?.();
        } catch {
            toast.error('Could not delete the call data');
        } finally {
            setDeleting(false);
        }
    };

    return (
        <AlertDialog open={open} onOpenChange={(next) => !deleting && setOpen(next)}>
            <AlertDialogTrigger asChild>
                <Button size="sm" variant="outline" className="gap-2">
                    <Trash2 className="h-4 w-4" />
                    Delete call data
                </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Delete this call&apos;s data?</AlertDialogTitle>
                    <AlertDialogDescription>
                        The recording, transcript, phone numbers, call context and QA results of
                        run {runId} are deleted for good. The call stays in your usage history with
                        its date, duration, status and cost, because billing records refer to it.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
                    <AlertDialogAction
                        onClick={(event) => {
                            // Keep the dialog open until the request settles.
                            event.preventDefault();
                            void handleDelete();
                        }}
                        disabled={deleting}
                        className={buttonVariants({ variant: 'destructive' })}
                    >
                        {deleting && <Loader2 className="h-4 w-4 animate-spin" />}
                        Delete call data
                    </AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
}
