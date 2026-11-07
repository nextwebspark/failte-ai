"use client";

import { Loader2, Play, Square } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useVoicePreview } from "@/hooks/useVoicePreview";
import { cn } from "@/lib/utils";

import { type VoiceChoices, type VoiceOption, voicePreviewPath } from "./voiceOptions";

function chipLabel(option: VoiceOption): string {
    return [option.name, option.gender].filter(Boolean).join(" · ");
}

/**
 * The agent's voice beside a few others (mocks/agent.png), each with a play
 * button that reads the greeting in that voice. Nothing plays or is generated
 * until a play button is pressed: every new sample costs a synthesis (the
 * server keeps each one, so a replay is free). Members who may change the
 * agent pick another voice here, after confirming.
 */
export function VoiceChips({
    workflowId,
    choices,
    readsGreeting,
    onSwitch,
}: {
    workflowId: number;
    choices: VoiceChoices;
    /** False when there is no spoken greeting (a recording, or none): the voices read a sample sentence. */
    readsGreeting: boolean;
    /** Absent for members who can't change the agent. */
    onSwitch?: (voice: string) => Promise<void>;
}) {
    const { playingId, previewError, toggle } = useVoicePreview();
    const [loadingId, setLoadingId] = useState<string | null>(null);
    const [confirming, setConfirming] = useState<VoiceOption | null>(null);
    const [saving, setSaving] = useState(false);
    const chipButtons = useRef(new Map<string, HTMLButtonElement>());

    const options = [choices.current, ...choices.alternatives];
    const what = readsGreeting ? "your greeting" : "a sample sentence";

    async function play(option: VoiceOption) {
        if (playingId !== option.value) setLoadingId(option.value);
        try {
            await toggle(option.value, voicePreviewPath(workflowId, option.previewVoiceId));
        } finally {
            setLoadingId((current) => (current === option.value ? null : current));
        }
    }

    function cancel() {
        const value = confirming?.value;
        setConfirming(null);
        if (value) chipButtons.current.get(value)?.focus();
    }

    async function confirm() {
        if (!confirming || !onSwitch) return;
        setSaving(true);
        try {
            await onSwitch(confirming.value);
            toast.success(
                `Your agent now speaks as ${confirming.name} on test calls. Publish the agent to use it on phone calls.`,
            );
            setConfirming(null);
        } catch (error) {
            toast.error(error instanceof Error ? error.message : "Couldn't change the voice. Please try again.");
        } finally {
            setSaving(false);
        }
    }

    return (
        <div className="flex flex-col gap-2">
            <ul aria-label="Voices" className="flex flex-wrap gap-2">
                {options.map((option) => {
                    const isCurrent = option === choices.current;
                    const playing = playingId === option.value;
                    const loading = loadingId === option.value && !playing;
                    const label = chipLabel(option);
                    return (
                        <li
                            key={option.value}
                            className={cn(
                                "inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border py-1 pl-1 pr-3 text-caption font-semibold",
                                isCurrent ? "border-brand bg-brand-dim text-brand" : "border-line bg-panel text-foreground",
                            )}
                        >
                            <button
                                type="button"
                                onClick={() => void play(option)}
                                aria-label={playing ? `Stop ${option.name}` : `Hear ${option.name} read ${what}`}
                                className="grid size-[26px] shrink-0 place-items-center rounded-full bg-panel-2 text-foreground outline-none transition-colors hover:bg-line focus-visible:ring-2 focus-visible:ring-ring"
                            >
                                {loading ? (
                                    <Loader2 className="size-3 animate-spin" aria-hidden />
                                ) : playing ? (
                                    <Square className="size-2.5 fill-current" aria-hidden />
                                ) : (
                                    <Play className="size-3 fill-current" aria-hidden />
                                )}
                            </button>
                            {isCurrent ? (
                                <span className="truncate">
                                    <span className="sr-only">Your agent&apos;s voice: </span>
                                    {label}
                                </span>
                            ) : onSwitch ? (
                                <button
                                    type="button"
                                    ref={(node) => {
                                        if (node) chipButtons.current.set(option.value, node);
                                        else chipButtons.current.delete(option.value);
                                    }}
                                    onClick={() => setConfirming(option)}
                                    disabled={saving}
                                    aria-label={`Use ${option.name}${option.gender ? `, ${option.gender.toLowerCase()}` : ""}`}
                                    className="truncate rounded-sm outline-none underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:ring-ring"
                                >
                                    {label}
                                </button>
                            ) : (
                                <span className="truncate">{label}</span>
                            )}
                        </li>
                    );
                })}
            </ul>
            <p className="text-caption text-ink-3">
                {readsGreeting
                    ? "Press play to hear each voice read your greeting."
                    : "Press play to hear each voice read a short sample sentence."}
                {onSwitch && " Choose a name to switch."}
            </p>
            {previewError && (
                <p className="text-caption text-danger" role="alert">
                    Couldn&apos;t play that voice. Try again in a moment.
                </p>
            )}
            {confirming && (
                <div role="group" aria-label="Change the voice" className="flex flex-col gap-2 rounded-lg border border-line bg-panel-2 p-3">
                    <p className="text-caption text-foreground">
                        Switch your agent to {confirming.name}? Test calls use it straight away; phone calls switch when the
                        agent is next published.
                    </p>
                    <div className="flex flex-wrap gap-2">
                        <Button type="button" size="sm" onClick={() => void confirm()} disabled={saving} autoFocus>
                            {saving && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
                            Use {confirming.name}
                        </Button>
                        <Button type="button" size="sm" variant="outline" onClick={cancel} disabled={saving}>
                            Cancel
                        </Button>
                    </div>
                </div>
            )}
        </div>
    );
}
