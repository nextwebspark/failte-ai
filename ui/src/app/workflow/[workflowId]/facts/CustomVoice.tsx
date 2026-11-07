"use client";

/**
 * "Custom voice": a voice of your own is coming soon. An owner who already
 * cloned a voice elsewhere (ElevenLabs, Cartesia…) can ask us to set it up;
 * the team does it by hand. We never ask for or accept a provider key.
 */
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
    getCustomVoiceApiV1WorkflowWorkflowIdCustomVoiceGet,
    requestCustomVoiceApiV1WorkflowWorkflowIdCustomVoicePost,
} from "@/client/sdk.gen";
import type { CustomVoiceRequest, CustomVoiceRequestIn } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { detailFromError } from "@/lib/apiError";

const PROVIDERS: { value: CustomVoiceRequestIn["provider"]; label: string }[] = [
    { value: "elevenlabs", label: "ElevenLabs" },
    { value: "cartesia", label: "Cartesia" },
    { value: "other", label: "Another provider" },
];

export function requestedOn(iso: string): string {
    return new Date(iso).toLocaleDateString("en-IE", { day: "numeric", month: "long" });
}

export function CustomVoice({ workflowId, canRequest }: { workflowId: number; canRequest: boolean }) {
    const [request, setRequest] = useState<CustomVoiceRequest | null>(null);
    const [open, setOpen] = useState(false);

    const load = useCallback(async () => {
        try {
            const res = await getCustomVoiceApiV1WorkflowWorkflowIdCustomVoiceGet({ path: { workflow_id: workflowId } });
            setRequest(res.data?.request ?? null);
        } catch {
            setRequest(null);
        }
    }, [workflowId]);

    useEffect(() => {
        void load();
    }, [load]);

    return (
        <div className="rounded-xl border border-dashed border-line px-3.5 py-3">
            <div className="flex items-center gap-2">
                <p className="text-[13px] font-semibold text-foreground">Your own voice</p>
                <span className="rounded-full bg-sky-dim px-2 py-0.5 text-[11px] font-semibold text-sky">Coming soon</span>
            </div>
            {request ? (
                <p className="mt-1 text-[12.5px] leading-relaxed text-ink-2">
                    You asked us on {requestedOn(request.requested_at)} to set up
                    {request.voice_name ? ` "${request.voice_name}"` : " your voice"}. We&apos;ll be in touch to finish it.
                </p>
            ) : (
                <p className="mt-1 text-[12.5px] leading-relaxed text-ink-2">
                    Soon you&apos;ll be able to record your own voice here.
                    {canRequest && " Already have a cloned voice with ElevenLabs or Cartesia? We can set it up for you."}
                </p>
            )}
            {canRequest && (
                <button
                    type="button"
                    onClick={() => setOpen(true)}
                    className="mt-1.5 text-[13px] font-medium text-brand underline-offset-2 hover:underline"
                >
                    {request ? "Send another request" : "I already have a cloned voice"}
                </button>
            )}
            {open && (
                <RequestDialog
                    workflowId={workflowId}
                    onClose={() => setOpen(false)}
                    onSent={(sent) => {
                        setRequest(sent);
                        setOpen(false);
                    }}
                />
            )}
        </div>
    );
}

function RequestDialog({
    workflowId,
    onClose,
    onSent,
}: {
    workflowId: number;
    onClose: () => void;
    onSent: (request: CustomVoiceRequest) => void;
}) {
    const [provider, setProvider] = useState<CustomVoiceRequestIn["provider"]>("elevenlabs");
    const [voiceId, setVoiceId] = useState("");
    const [voiceName, setVoiceName] = useState("");
    const [note, setNote] = useState("");
    const [consent, setConsent] = useState(false);
    const [sending, setSending] = useState(false);

    const send = async () => {
        setSending(true);
        try {
            const res = await requestCustomVoiceApiV1WorkflowWorkflowIdCustomVoicePost({
                path: { workflow_id: workflowId },
                body: {
                    provider,
                    voice_id: voiceId.trim(),
                    voice_name: voiceName.trim() || null,
                    note: note.trim() || null,
                    consent,
                },
            });
            if (res.error || !res.data?.request) {
                toast.error(detailFromError(res.error, "Couldn't send the request. Please try again."));
                return;
            }
            toast.success("Request sent. We'll be in touch to set up your voice.");
            onSent(res.data.request);
        } catch {
            toast.error("Couldn't send the request. Please try again.");
        } finally {
            setSending(false);
        }
    };

    return (
        <Dialog open onOpenChange={(next) => !next && onClose()}>
            <DialogContent className="sm:max-w-md">
                <DialogHeader>
                    <DialogTitle>Use a voice you already have</DialogTitle>
                    <DialogDescription>
                        Tell us where your cloned voice is and we&apos;ll set it up for this agent. Don&apos;t send your password or
                        API key. We&apos;ll tell you how to share the voice with us.
                    </DialogDescription>
                </DialogHeader>
                <div className="flex flex-col gap-3.5">
                    <fieldset className="flex flex-col gap-1.5">
                        <legend className="mb-1.5 text-[13px] font-medium">Where is it?</legend>
                        <div className="flex flex-wrap gap-2">
                            {PROVIDERS.map((p) => (
                                <button
                                    key={p.value}
                                    type="button"
                                    aria-pressed={provider === p.value}
                                    onClick={() => setProvider(p.value)}
                                    className={
                                        provider === p.value
                                            ? "rounded-full border border-brand bg-brand-dim px-3 py-1 text-[13px] font-semibold text-brand"
                                            : "rounded-full border border-line px-3 py-1 text-[13px] text-ink-2 hover:bg-panel-2"
                                    }
                                >
                                    {p.label}
                                </button>
                            ))}
                        </div>
                    </fieldset>
                    <div className="flex flex-col gap-1.5">
                        <Label htmlFor="custom-voice-id">Voice ID</Label>
                        <Input
                            id="custom-voice-id"
                            value={voiceId}
                            onChange={(e) => setVoiceId(e.target.value)}
                            placeholder="e.g. pNInz6obpgDQGcFmaJgB"
                            maxLength={200}
                            autoComplete="off"
                        />
                        <p className="text-[12px] text-ink-3">Shown next to the voice in your provider&apos;s voice list.</p>
                    </div>
                    <div className="flex flex-col gap-1.5">
                        <Label htmlFor="custom-voice-name">Voice name (optional)</Label>
                        <Input
                            id="custom-voice-name"
                            value={voiceName}
                            onChange={(e) => setVoiceName(e.target.value)}
                            placeholder="e.g. Pat Murphy"
                            maxLength={120}
                        />
                    </div>
                    <div className="flex flex-col gap-1.5">
                        <Label htmlFor="custom-voice-note">Anything else? (optional)</Label>
                        <Textarea
                            id="custom-voice-note"
                            value={note}
                            onChange={(e) => setNote(e.target.value)}
                            maxLength={1000}
                            rows={2}
                        />
                    </div>
                    <label className="flex items-start gap-2.5 text-[13px] leading-snug text-ink-2">
                        <Checkbox
                            checked={consent}
                            onCheckedChange={(checked) => setConsent(checked === true)}
                            className="mt-0.5"
                            aria-label="I confirm this is my own voice, or I have the speaker's written permission"
                        />
                        <span>
                            This is my own voice, or I have the speaker&apos;s written permission to use it for this business&apos;s
                            phone agent. Your agent will still tell callers it&apos;s an AI.
                        </span>
                    </label>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={onClose} disabled={sending}>
                        Cancel
                    </Button>
                    <Button onClick={send} disabled={sending || !voiceId.trim() || !consent}>
                        {sending ? "Sending…" : "Send request"}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
