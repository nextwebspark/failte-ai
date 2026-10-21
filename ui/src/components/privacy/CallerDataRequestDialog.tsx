'use client';

import { Download, Loader2, ShieldCheck, Trash2 } from 'lucide-react';
import { useState } from 'react';

import {
    eraseCallerDataApiV1OrganizationsUsageSubjectDataErasePost,
    getCallerDataApiV1OrganizationsUsageSubjectDataGet,
} from '@/client/sdk.gen';
import type { SubjectErasureResponse } from '@/client/types.gen';
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button, buttonVariants } from '@/components/ui/button';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { detailFromError } from '@/lib/apiError';

type Busy = 'download' | 'erase' | null;

function saveJson(data: unknown, filename: string) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
}

function plural(count: number, one: string, many = `${one}s`) {
    return `${count} ${count === 1 ? one : many}`;
}

function were(count: number) {
    return count === 1 ? 'was' : 'were';
}

function ErasureSummary({ result }: { result: SubjectErasureResponse }) {
    const lines = [
        `${plural(result.calls_erased, 'call')} erased (${plural(result.objects_deleted, 'stored file')} deleted)`,
        `${plural(result.queued_calls_deleted, 'campaign contact')} not yet called removed`,
        `${plural(result.queued_calls_cleared, 'campaign contact row')} cleared`,
        `${plural(result.campaign_list_rows_removed, 'row')} removed from ${plural(result.campaign_lists_rewritten, 'contact list')}`,
    ];
    const warnings = [
        result.calls_in_progress.length > 0
            && `${plural(result.calls_in_progress.length, 'call')} still in progress (${result.calls_in_progress.join(', ')}) ${were(result.calls_in_progress.length)} skipped. Erase again once they end.`,
        result.calls_failed.length > 0
            && `The recordings of ${plural(result.calls_failed.length, 'call')} (${result.calls_failed.join(', ')}) could not be deleted. Try again shortly.`,
        result.queued_calls_in_progress > 0
            && `${plural(result.queued_calls_in_progress, 'campaign contact')} being dialled right now ${were(result.queued_calls_in_progress)} skipped. Erase again once the call ends.`,
        result.campaign_lists_failed.length > 0
            && `The contact lists of ${plural(result.campaign_lists_failed.length, 'campaign')} (${result.campaign_lists_failed.join(', ')}) could not be rewritten. Try again shortly.`,
    ].filter((warning): warning is string => Boolean(warning));

    return (
        <div className="space-y-2 rounded-lg border border-border bg-muted/40 p-3 text-sm" role="status">
            <p className="font-medium text-foreground">Erased data for {result.number}</p>
            <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                {lines.map((line) => <li key={line}>{line}</li>)}
            </ul>
            {warnings.length > 0 && (
                <ul className="list-disc space-y-1 pl-5 text-destructive">
                    {warnings.map((warning) => <li key={warning}>{warning}</li>)}
                </ul>
            )}
        </div>
    );
}

/** Answer a caller's request: download everything stored about their phone
 *  number (GDPR access request) or erase it (erasure request). */
export function CallerDataRequestDialog() {
    const [open, setOpen] = useState(false);
    const [number, setNumber] = useState('');
    const [busy, setBusy] = useState<Busy>(null);
    const [confirmOpen, setConfirmOpen] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);
    const [erasure, setErasure] = useState<SubjectErasureResponse | null>(null);

    const trimmed = number.trim();

    const reset = () => {
        setError(null);
        setNotice(null);
        setErasure(null);
    };

    const handleDownload = async () => {
        reset();
        setBusy('download');
        try {
            const response = await getCallerDataApiV1OrganizationsUsageSubjectDataGet({
                query: { number: trimmed },
            });
            if (response.error || !response.data) {
                setError(detailFromError(response.error, 'Could not export the caller data'));
                return;
            }
            const data = response.data;
            const digits = data.number.replace(/[^0-9a-zA-Z]+/g, '') || 'caller';
            saveJson(data, `caller-data-${digits}.json`);
            setNotice(
                `Downloaded ${plural(data.calls.length, 'call')} and ${plural(data.queued_calls.length, 'campaign contact')} for ${data.number}. `
                + 'Recording links in the file expire after one hour.'
                + (data.truncated ? ' More calls matched than one export holds; the oldest are included.' : ''),
            );
        } catch {
            setError('Could not export the caller data');
        } finally {
            setBusy(null);
        }
    };

    const handleErase = async () => {
        reset();
        setBusy('erase');
        try {
            const response = await eraseCallerDataApiV1OrganizationsUsageSubjectDataErasePost({
                body: { number: trimmed },
            });
            if (response.error || !response.data) {
                setError(detailFromError(response.error, 'Could not erase the caller data'));
                return;
            }
            setErasure(response.data);
        } catch {
            setError('Could not erase the caller data');
        } finally {
            setBusy(null);
            setConfirmOpen(false);
        }
    };

    return (
        <Dialog
            open={open}
            onOpenChange={(next) => {
                if (busy) return;
                setOpen(next);
                if (!next) {
                    setNumber('');
                    reset();
                }
            }}
        >
            <DialogTrigger asChild>
                <Button variant="outline" size="sm" className="gap-2">
                    <ShieldCheck className="h-4 w-4" />
                    Caller data request
                </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-lg">
                <DialogHeader>
                    <DialogTitle>Caller data request</DialogTitle>
                    <DialogDescription>
                        When a caller asks for a copy of their data or for it to be deleted, enter
                        their phone number. This covers calls from and to that number and its
                        campaign contacts, across all your agents.
                    </DialogDescription>
                </DialogHeader>

                <form
                    className="space-y-4"
                    onSubmit={(event) => {
                        event.preventDefault();
                        if (trimmed && !busy) void handleDownload();
                    }}
                >
                    <div className="space-y-2">
                        <Label htmlFor="caller-data-number">Caller&apos;s phone number</Label>
                        <Input
                            id="caller-data-number"
                            value={number}
                            onChange={(event) => {
                                setNumber(event.target.value);
                                reset();
                            }}
                            placeholder="+353 87 123 4567"
                            autoComplete="off"
                            maxLength={255}
                        />
                    </div>

                    {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
                    {notice && <p className="text-sm text-muted-foreground" role="status">{notice}</p>}
                    {erasure && <ErasureSummary result={erasure} />}

                    <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                        <Button
                            type="button"
                            variant="outline"
                            className="gap-2"
                            disabled={!trimmed || busy !== null}
                            onClick={() => setConfirmOpen(true)}
                        >
                            <Trash2 className="h-4 w-4" />
                            Erase all data
                        </Button>
                        <Button type="submit" className="gap-2" disabled={!trimmed || busy !== null}>
                            {busy === 'download'
                                ? <Loader2 className="h-4 w-4 animate-spin" />
                                : <Download className="h-4 w-4" />}
                            Download data (JSON)
                        </Button>
                    </div>
                </form>

                <AlertDialog open={confirmOpen} onOpenChange={(next) => busy === null && setConfirmOpen(next)}>
                    <AlertDialogContent>
                        <AlertDialogHeader>
                            <AlertDialogTitle>Erase all data for {trimmed}?</AlertDialogTitle>
                            <AlertDialogDescription>
                                Recordings, transcripts, call details and the phone number are deleted
                                for good from every call with this number. Campaign contacts not yet
                                called are removed, and the number is removed from uploaded contact
                                lists. Calls stay in your usage history with their date, duration,
                                status and cost for billing. This can&apos;t be undone.
                            </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                            <AlertDialogCancel disabled={busy !== null}>Cancel</AlertDialogCancel>
                            <AlertDialogAction
                                onClick={(event) => {
                                    event.preventDefault();
                                    void handleErase();
                                }}
                                disabled={busy !== null}
                                className={buttonVariants({ variant: 'destructive' })}
                            >
                                {busy === 'erase' && <Loader2 className="h-4 w-4 animate-spin" />}
                                Erase all data
                            </AlertDialogAction>
                        </AlertDialogFooter>
                    </AlertDialogContent>
                </AlertDialog>
            </DialogContent>
        </Dialog>
    );
}
