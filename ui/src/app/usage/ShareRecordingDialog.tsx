"use client";

import { Check, Copy, Link2, Share2 } from "lucide-react";
import { useCallback, useEffect, useId, useState } from "react";
import { toast } from "sonner";

import {
    createRecordingShareApiV1CallsRunIdRecordingSharesPost,
    listRecordingSharesApiV1CallsRunIdRecordingSharesGet,
    revokeRecordingShareApiV1CallsRunIdRecordingSharesShareIdDelete,
} from "@/client/sdk.gen";
import type { RecordingShare, ShareExpiry } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { detailFromError } from "@/lib/apiError";
import { copyTextToClipboard } from "@/lib/clipboard";

import { formatCallWhen } from "./callsView";

const EXPIRY_OPTIONS: { value: ShareExpiry; label: string }[] = [
    { value: "7d", label: "7 days" },
    { value: "24h", label: "24 hours" },
];

type Shares = { state: "loading" } | { state: "error" } | { state: "ready"; shares: RecordingShare[] };

/**
 * "Share recording": make a link anyone can play without signing in, for 24
 * hours or 7 days; copy it; see the links still working and turn any off.
 * The link itself is shown once: only a fingerprint of it is stored.
 */
export function ShareRecordingDialog({ runId, timezone }: { runId: number; timezone: string }) {
    const [open, setOpen] = useState(false);
    const [expiry, setExpiry] = useState<ShareExpiry>("7d");
    const [creating, setCreating] = useState(false);
    const [made, setMade] = useState<{ url: string; expiresAt: string } | null>(null);
    const [copied, setCopied] = useState(false);
    const [shares, setShares] = useState<Shares>({ state: "loading" });
    const [revoking, setRevoking] = useState<string | null>(null);
    const expiryId = useId();
    const linkId = useId();

    const load = useCallback(async () => {
        setShares({ state: "loading" });
        try {
            const response = await listRecordingSharesApiV1CallsRunIdRecordingSharesGet({ path: { run_id: runId } });
            setShares(response.data ? { state: "ready", shares: response.data.shares } : { state: "error" });
        } catch {
            setShares({ state: "error" });
        }
    }, [runId]);

    useEffect(() => {
        if (open) {
            setMade(null);
            setCopied(false);
            void load();
        }
    }, [open, load]);

    const create = async () => {
        setCreating(true);
        try {
            const response = await createRecordingShareApiV1CallsRunIdRecordingSharesPost({
                path: { run_id: runId },
                body: { expires_in: expiry },
            });
            if (!response.data) {
                toast.error(detailFromError(response.error, "We couldn't make a link. Please try again."));
                return;
            }
            setMade({ url: response.data.url, expiresAt: response.data.expires_at });
            setCopied(false);
            void load();
        } catch {
            toast.error("We couldn't make a link. Please try again.");
        } finally {
            setCreating(false);
        }
    };

    const copy = async () => {
        if (!made) return;
        try {
            await copyTextToClipboard(made.url);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch {
            toast.error("Couldn't copy the link");
        }
    };

    const revoke = async (share: RecordingShare) => {
        setRevoking(share.id);
        try {
            const response = await revokeRecordingShareApiV1CallsRunIdRecordingSharesShareIdDelete({
                path: { run_id: runId, share_id: share.id },
            });
            if (response.error) {
                toast.error(detailFromError(response.error, "We couldn't turn that link off. Please try again."));
                return;
            }
            toast.success("Link turned off. It stops working straight away.");
            void load();
        } catch {
            toast.error("We couldn't turn that link off. Please try again.");
        } finally {
            setRevoking(null);
        }
    };

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
                <Button variant="outline" className="h-10 sm:h-9">
                    <Share2 aria-hidden />
                    Share recording
                </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-md">
                <DialogHeader>
                    <DialogTitle>Share this recording</DialogTitle>
                    <DialogDescription>
                        Anyone with the link can listen, without signing in. They see your business name and the
                        date of the call, never the caller&apos;s number.
                    </DialogDescription>
                </DialogHeader>

                <div className="flex flex-col gap-3">
                    <fieldset>
                        <legend id={expiryId} className="mb-2 text-sm font-medium">The link works for</legend>
                        <RadioGroup
                            aria-labelledby={expiryId}
                            value={expiry}
                            onValueChange={(value) => setExpiry(value as ShareExpiry)}
                            className="flex flex-wrap gap-4"
                        >
                            {EXPIRY_OPTIONS.map((option) => (
                                <div key={option.value} className="flex min-h-10 items-center gap-2 sm:min-h-0">
                                    <RadioGroupItem id={`${expiryId}-${option.value}`} value={option.value} />
                                    <Label htmlFor={`${expiryId}-${option.value}`} className="font-normal">
                                        {option.label}
                                    </Label>
                                </div>
                            ))}
                        </RadioGroup>
                    </fieldset>

                    {made ? (
                        <div className="flex flex-col gap-2 rounded-lg border border-line bg-panel-2 p-3">
                            <Label htmlFor={linkId} className="text-[13px]">Your link</Label>
                            <div className="flex gap-2">
                                <input
                                    id={linkId}
                                    readOnly
                                    value={made.url}
                                    onFocus={(event) => event.currentTarget.select()}
                                    className="h-10 min-w-0 flex-1 rounded-md border border-line bg-panel px-2.5 text-[13px] text-foreground outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/30 sm:h-9"
                                />
                                <Button className="h-10 sm:h-9" onClick={copy}>
                                    {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
                                    {copied ? "Copied" : "Copy link"}
                                </Button>
                            </div>
                            <p className="text-[12.5px] text-ink-3" role="status">
                                Works until {formatCallWhen(made.expiresAt, timezone)}. Copy it now: for safety we don&apos;t
                                keep a copy of the link.
                            </p>
                        </div>
                    ) : (
                        <Button className="h-10 self-start sm:h-9" onClick={create} disabled={creating}>
                            <Link2 aria-hidden />
                            {creating ? "Making the link…" : "Make a link"}
                        </Button>
                    )}
                    {made && (
                        <Button variant="outline" className="h-10 self-start sm:h-9" onClick={create} disabled={creating}>
                            <Link2 aria-hidden />
                            {creating ? "Making the link…" : "Make another link"}
                        </Button>
                    )}
                </div>

                <section aria-labelledby={`${expiryId}-active`} className="border-t border-line-soft pt-4">
                    <h3 id={`${expiryId}-active`} className="mb-2 text-sm font-semibold">Links that work now</h3>
                    {shares.state === "loading" ? (
                        <p className="text-sm text-ink-3">Loading…</p>
                    ) : shares.state === "error" ? (
                        <p className="text-sm text-ink-3">
                            We couldn&apos;t load the links.{" "}
                            <button type="button" onClick={() => void load()} className="font-semibold text-brand underline-offset-2 hover:underline">
                                Try again
                            </button>
                        </p>
                    ) : shares.shares.length === 0 ? (
                        <p className="text-sm text-ink-3">None. Nobody outside your team can listen to this call.</p>
                    ) : (
                        <ul className="flex flex-col divide-y divide-line-soft">
                            {shares.shares.map((share) => (
                                <li key={share.id} className="flex items-center justify-between gap-3 py-2">
                                    <div className="min-w-0 text-[13px]">
                                        <p className="text-foreground">
                                            Works until {formatCallWhen(share.expires_at, timezone)}
                                        </p>
                                        <p className="text-ink-3">
                                            Made {formatCallWhen(share.created_at, timezone)}
                                            {share.created_by ? ` by ${share.created_by}` : ""}
                                        </p>
                                    </div>
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        className="h-10 flex-none sm:h-8"
                                        onClick={() => revoke(share)}
                                        disabled={revoking === share.id}
                                        aria-label={`Revoke the link that works until ${formatCallWhen(share.expires_at, timezone)}`}
                                    >
                                        {revoking === share.id ? "Revoking…" : "Revoke"}
                                    </Button>
                                </li>
                            ))}
                        </ul>
                    )}
                </section>
            </DialogContent>
        </Dialog>
    );
}
