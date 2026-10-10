"use client";

import * as RadioGroupPrimitive from "@radix-ui/react-radio-group";
import { Check, Play, Square } from "lucide-react";

import type { PlatformCatalogOption } from "@/client/types.gen";
import { useVoicePreview } from "@/hooks/useVoicePreview";
import { cn } from "@/lib/utils";

interface GeminiLiveVoicePickerProps {
    voices: PlatformCatalogOption[];
    value: string;
    onChange: (voice: string) => void;
    disabled?: boolean;
    labelledBy?: string;
}

const capitalize = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);

/**
 * The speech-to-speech voices as cards (arrow keys move between them), with a
 * sample next to each voice the catalog has one for.
 */
export function GeminiLiveVoicePicker({
    voices,
    value,
    onChange,
    disabled = false,
    labelledBy,
}: GeminiLiveVoicePickerProps) {
    const { playingId, previewError, toggle } = useVoicePreview();

    return (
        <div className="space-y-2">
            <RadioGroupPrimitive.Root
                value={value}
                onValueChange={onChange}
                disabled={disabled}
                aria-labelledby={labelledBy}
                className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3"
            >
                {voices.map((voice) => {
                    const selected = voice.id === value;
                    const traits = [voice.gender && capitalize(voice.gender), voice.description]
                        .filter(Boolean)
                        .join(" · ");
                    return (
                        <RadioGroupPrimitive.Item
                            key={voice.id}
                            value={voice.id}
                            className={cn(
                                "flex items-center justify-between gap-2 rounded-lg border p-3 text-left transition-colors",
                                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                                "disabled:cursor-not-allowed disabled:opacity-60",
                                selected ? "border-primary ring-1 ring-primary" : "border-border hover:bg-accent",
                            )}
                        >
                            <span className="min-w-0">
                                <span className="block font-medium">{voice.label}</span>
                                {traits && <span className="block truncate text-xs text-muted-foreground">{traits}</span>}
                            </span>
                            {selected && <Check className="h-4 w-4 shrink-0 text-primary" />}
                        </RadioGroupPrimitive.Item>
                    );
                })}
            </RadioGroupPrimitive.Root>
            {voices.some((voice) => voice.preview_url) && (
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span>Listen:</span>
                    {voices
                        .filter((voice) => voice.preview_url)
                        .map((voice) => {
                            const playing = playingId === voice.id;
                            return (
                                <button
                                    key={voice.id}
                                    type="button"
                                    aria-label={playing ? `Stop ${voice.label} sample` : `Play ${voice.label} sample`}
                                    onClick={() => void toggle(voice.id, voice.preview_url)}
                                    className="inline-flex items-center gap-1 rounded-full border px-2 py-1 hover:bg-muted"
                                >
                                    {playing ? <Square className="h-3 w-3" /> : <Play className="h-3 w-3" />}
                                    {voice.label}
                                </button>
                            );
                        })}
                </div>
            )}
            {previewError && <p className="text-xs text-destructive">{previewError}</p>}
        </div>
    );
}
