"use client";

import * as RadioGroupPrimitive from "@radix-ui/react-radio-group";
import { Check, Play, Square } from "lucide-react";
import { useState } from "react";

import { useVoicePreview } from "@/hooks/useVoicePreview";
import { cn } from "@/lib/utils";

export interface VoiceCardOption {
    id: string;
    label: string;
    gender?: string | null;
    description?: string | null;
    preview_url?: string | null;
}

interface VoiceCardPickerProps {
    voices: VoiceCardOption[];
    value: string;
    onChange: (voice: string) => void;
    disabled?: boolean;
    labelledBy?: string;
    // Shown under the cards when any voice has a sample.
    sampleNote?: string;
}

const capitalize = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);

/**
 * Voices as cards (arrow keys move between them), each with its own sample
 * button, and a filter by voice gender. Both speech-to-speech and
 * text-to-speech voices are picked with it, so the two modes look the same.
 */
export function VoiceCardPicker({
    voices,
    value,
    onChange,
    disabled = false,
    labelledBy,
    sampleNote,
}: VoiceCardPickerProps) {
    const { playingId, previewError, toggle } = useVoicePreview();
    const [gender, setGender] = useState<string>("all");

    const genders = [...new Set(voices.map((voice) => voice.gender).filter((g): g is string => Boolean(g)))].sort();
    const shown = gender === "all" ? voices : voices.filter((voice) => voice.gender === gender);
    const selected = voices.find((voice) => voice.id === value);
    const hasSamples = voices.some((voice) => voice.preview_url);

    return (
        <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm text-muted-foreground">
                    {selected ? (
                        <>
                            Selected: <span className="font-medium text-foreground">{selected.label}</span>.
                        </>
                    ) : (
                        "Choose a voice."
                    )}
                    {hasSamples && " Press play on any voice to hear it."}
                </p>
                {genders.length > 1 && (
                    <div role="group" aria-label="Show voices" className="inline-flex rounded-md border p-0.5 text-xs">
                        {["all", ...genders].map((option) => {
                            const count = option === "all"
                                ? voices.length
                                : voices.filter((voice) => voice.gender === option).length;
                            return (
                                <button
                                    key={option}
                                    type="button"
                                    aria-pressed={gender === option}
                                    onClick={() => setGender(option)}
                                    className={cn(
                                        "rounded px-2.5 py-1 transition-colors",
                                        gender === option ? "bg-primary text-primary-foreground" : "hover:bg-muted",
                                    )}
                                >
                                    {option === "all" ? "All" : capitalize(option)} ({count})
                                </button>
                            );
                        })}
                    </div>
                )}
            </div>

            <RadioGroupPrimitive.Root
                value={value}
                onValueChange={onChange}
                disabled={disabled}
                aria-labelledby={labelledBy}
                className="grid gap-2 sm:grid-cols-2"
            >
                {shown.map((voice) => {
                    const isSelected = voice.id === value;
                    const playing = playingId === voice.id;
                    const traits = [voice.gender && capitalize(voice.gender), voice.description]
                        .filter(Boolean)
                        .join(" · ");
                    return (
                        <div
                            key={voice.id}
                            className={cn(
                                "relative rounded-lg border transition-colors",
                                isSelected ? "border-primary ring-1 ring-primary" : "border-border hover:bg-accent",
                                playing && !isSelected && "border-primary/60",
                            )}
                        >
                            <RadioGroupPrimitive.Item
                                value={voice.id}
                                className={cn(
                                    "flex w-full items-center gap-3 rounded-lg p-3 text-left",
                                    voice.preview_url && "pr-14",
                                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                                    "disabled:cursor-not-allowed disabled:opacity-60",
                                )}
                            >
                                <span
                                    aria-hidden
                                    className={cn(
                                        "flex h-4 w-4 shrink-0 items-center justify-center rounded-full border",
                                        isSelected && "border-primary bg-primary text-primary-foreground",
                                    )}
                                >
                                    {isSelected && <Check className="h-3 w-3" />}
                                </span>
                                <span className="min-w-0">
                                    <span className="block truncate font-medium">{voice.label}</span>
                                    {traits && <span className="block truncate text-xs text-muted-foreground">{traits}</span>}
                                </span>
                            </RadioGroupPrimitive.Item>
                            {/* A sibling, not a child: a button inside the radio would nest controls. */}
                            {voice.preview_url && (
                                <button
                                    type="button"
                                    aria-label={playing ? `Stop ${voice.label} sample` : `Play ${voice.label} sample`}
                                    onClick={() => void toggle(voice.id, voice.preview_url)}
                                    className={cn(
                                        "absolute right-3 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full border transition-colors",
                                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                                        playing ? "border-primary bg-primary text-primary-foreground" : "bg-background hover:bg-muted",
                                    )}
                                >
                                    {playing ? <Square className="h-3.5 w-3.5" /> : <Play className="ml-0.5 h-3.5 w-3.5" />}
                                </button>
                            )}
                        </div>
                    );
                })}
            </RadioGroupPrimitive.Root>

            {selected && !shown.includes(selected) && (
                <p className="text-xs text-muted-foreground">
                    {selected.label} is selected but hidden by the filter.
                </p>
            )}
            {hasSamples && sampleNote && <p className="text-xs text-muted-foreground">{sampleNote}</p>}
            {previewError && <p className="text-xs text-destructive">{previewError}</p>}
        </div>
    );
}
