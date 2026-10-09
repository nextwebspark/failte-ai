"use client";

import { Check, Play, Square } from "lucide-react";

import type { PlatformCatalogOption } from "@/client/types.gen";
import { useVoicePreview } from "@/hooks/useVoicePreview";
import { cn } from "@/lib/utils";

interface GeminiLiveVoicePickerProps {
    voices: PlatformCatalogOption[];
    value: string;
    onChange: (voice: string) => void;
    disabled?: boolean;
}

const capitalize = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);

/** The speech-to-speech voices as cards, with a sample where the catalog has one. */
export function GeminiLiveVoicePicker({ voices, value, onChange, disabled = false }: GeminiLiveVoicePickerProps) {
    const { playingId, previewError, toggle } = useVoicePreview();

    return (
        <div className="space-y-2">
            <div role="radiogroup" aria-label="Voice" className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {voices.map((voice) => {
                    const selected = voice.id === value;
                    const playing = playingId === voice.id;
                    const traits = [voice.gender && capitalize(voice.gender), voice.description]
                        .filter(Boolean)
                        .join(" · ");
                    return (
                        <div
                            key={voice.id}
                            className={cn(
                                "flex items-center gap-3 rounded-lg border p-3 transition-colors",
                                selected ? "border-primary ring-1 ring-primary" : "border-border",
                                disabled ? "opacity-60" : "hover:bg-accent",
                            )}
                        >
                            {voice.preview_url ? (
                                <button
                                    type="button"
                                    aria-label={playing ? `Stop ${voice.label} sample` : `Play ${voice.label} sample`}
                                    onClick={() => void toggle(voice.id, voice.preview_url)}
                                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border hover:bg-muted"
                                >
                                    {playing ? <Square className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                                </button>
                            ) : null}
                            <button
                                type="button"
                                role="radio"
                                aria-checked={selected}
                                disabled={disabled}
                                onClick={() => onChange(voice.id)}
                                className="flex min-w-0 flex-1 items-center justify-between gap-2 text-left disabled:cursor-not-allowed"
                            >
                                <span className="min-w-0">
                                    <span className="block font-medium">{voice.label}</span>
                                    {traits && <span className="block truncate text-xs text-muted-foreground">{traits}</span>}
                                </span>
                                {selected && <Check className="h-4 w-4 shrink-0 text-primary" />}
                            </button>
                        </div>
                    );
                })}
            </div>
            {previewError && <p className="text-xs text-destructive">{previewError}</p>}
        </div>
    );
}
