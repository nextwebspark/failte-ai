"use client";

import * as RadioGroupPrimitive from "@radix-ui/react-radio-group";
import { Check, Play, Search, Square, Star } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useVoicePreview } from "@/hooks/useVoicePreview";
import { cn } from "@/lib/utils";
import { VOICE_TONES, voiceTone } from "@/lib/voiceFilters";

export interface VoiceCardOption {
    id: string;
    label: string;
    gender?: string | null;
    description?: string | null;
    preview_url?: string | null;
    recommended?: boolean | null;
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

interface Filters {
    tone: string;
    gender: string;
    recommended: boolean;
    search: string;
}

const NO_FILTERS: Filters = { tone: "all", gender: "all", recommended: false, search: "" };

const capitalize = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);

function matches(voice: VoiceCardOption, filters: Filters): boolean {
    const query = filters.search.trim().toLowerCase();
    return (
        (filters.tone === "all" || voiceTone(voice.description) === filters.tone)
        && (filters.gender === "all" || voice.gender === filters.gender)
        && (!filters.recommended || Boolean(voice.recommended))
        && (!query || voice.label.toLowerCase().includes(query) || (voice.description ?? "").toLowerCase().includes(query))
    );
}

/** A toggle button styled as a chip, shared by the voice and accent filters. */
export function FilterChip({
    pressed,
    onClick,
    children,
    disabled = false,
}: {
    pressed: boolean;
    onClick: () => void;
    children: React.ReactNode;
    disabled?: boolean;
}) {
    return (
        <button
            type="button"
            aria-pressed={pressed}
            onClick={onClick}
            disabled={disabled}
            className={cn(
                "inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                "disabled:cursor-not-allowed disabled:opacity-60",
                pressed ? "border-primary bg-primary text-primary-foreground" : "hover:bg-muted",
            )}
        >
            {children}
        </button>
    );
}

/**
 * Voices as cards (arrow keys move between them), each with its own sample
 * button, narrowed by tone, gender, a recommended shortlist or name. Both
 * speech-to-speech and text-to-speech voices are picked with it, so the two
 * modes look the same.
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
    const [filters, setFilters] = useState<Filters>(NO_FILTERS);
    const setFilter = (change: Partial<Filters>) => setFilters((current) => ({ ...current, ...change }));

    const genders = [...new Set(voices.map((voice) => voice.gender).filter((g): g is string => Boolean(g)))].sort();
    const tones = VOICE_TONES.filter((tone) => voices.some((voice) => voiceTone(voice.description) === tone.id));
    const hasRecommended = voices.some((voice) => voice.recommended);
    const shown = voices.filter((voice) => matches(voice, filters));
    // How many voices a chip would show, given the other filters.
    const count = (change: Partial<Filters>) =>
        voices.filter((voice) => matches(voice, { ...filters, ...change })).length;
    const filtered = JSON.stringify(filters) !== JSON.stringify(NO_FILTERS);
    const selected = voices.find((voice) => voice.id === value);
    const hasSamples = voices.some((voice) => voice.preview_url);

    return (
        <div className="space-y-3">
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

            <div className="space-y-2 rounded-lg border bg-muted/30 p-3">
                <div className="flex flex-wrap items-center gap-2">
                    <div className="relative min-w-40 flex-1">
                        <Search aria-hidden className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                        <Input
                            type="search"
                            aria-label="Search voices"
                            placeholder="Search by name or style"
                            value={filters.search}
                            onChange={(event) => setFilter({ search: event.target.value })}
                            className="h-8 pl-8 text-sm"
                        />
                    </div>
                    {hasRecommended && (
                        <FilterChip
                            pressed={filters.recommended}
                            onClick={() => setFilter({ recommended: !filters.recommended })}
                        >
                            <Star aria-hidden className="h-3 w-3" />
                            Recommended for calls
                        </FilterChip>
                    )}
                    {filtered && (
                        <Button type="button" variant="ghost" size="sm" className="h-8 text-xs" onClick={() => setFilters(NO_FILTERS)}>
                            Clear filters
                        </Button>
                    )}
                </div>
                {tones.length > 1 && (
                    <div role="group" aria-label="Tone" className="flex flex-wrap items-center gap-1.5">
                        <span className="mr-1 w-14 text-xs font-medium text-muted-foreground">Tone</span>
                        {[{ id: "all", label: "All" }, ...tones].map((tone) => {
                            const matching = count({ tone: tone.id });
                            const pressed = filters.tone === tone.id;
                            return (
                                <FilterChip
                                    key={tone.id}
                                    pressed={pressed}
                                    disabled={matching === 0 && !pressed}
                                    onClick={() => setFilter({ tone: tone.id })}
                                >
                                    {tone.label} ({matching})
                                </FilterChip>
                            );
                        })}
                    </div>
                )}
                {genders.length > 1 && (
                    <div role="group" aria-label="Gender" className="flex flex-wrap items-center gap-1.5">
                        <span className="mr-1 w-14 text-xs font-medium text-muted-foreground">Gender</span>
                        {["all", ...genders].map((gender) => {
                            const matching = count({ gender });
                            const pressed = filters.gender === gender;
                            return (
                                <FilterChip
                                    key={gender}
                                    pressed={pressed}
                                    disabled={matching === 0 && !pressed}
                                    onClick={() => setFilter({ gender })}
                                >
                                    {gender === "all" ? "All" : capitalize(gender)} ({matching})
                                </FilterChip>
                            );
                        })}
                    </div>
                )}
                {tones.length > 1 && (
                    <p className="text-xs text-muted-foreground">Tones group Google&apos;s one-word description of each voice.</p>
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
                                    <span className="flex items-center gap-1.5">
                                        <span className="truncate font-medium">{voice.label}</span>
                                        {voice.recommended && (
                                            <Star aria-label="Recommended" className="h-3 w-3 shrink-0 fill-current text-amber-500" />
                                        )}
                                    </span>
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

            {shown.length === 0 && (
                <p className="text-sm text-muted-foreground">
                    No voices match these filters.{" "}
                    <button type="button" className="underline" onClick={() => setFilters(NO_FILTERS)}>
                        Clear filters
                    </button>
                </p>
            )}
            {selected && !shown.includes(selected) && (
                <p className="text-xs text-muted-foreground">
                    {selected.label} is selected but hidden by the filters.
                </p>
            )}
            {hasSamples && sampleNote && <p className="text-xs text-muted-foreground">{sampleNote}</p>}
            {previewError && <p className="text-xs text-destructive">{previewError}</p>}
        </div>
    );
}
