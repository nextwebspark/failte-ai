"use client";

import { format, startOfDay, subDays } from "date-fns";
import { CalendarDays, Check, ChevronDown, Search, X } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import type { DateRange } from "react-day-picker";

import { CHIP, CHIP_OFF, CHIP_ON } from "@/app/usage/CallsFilters";
import type { FollowUpKind, FollowUpListResponse, FollowUpStatus } from "@/client/types.gen";
import { FOLLOW_UP_KINDS, FOLLOW_UP_WORDS, RULE_CLASSES } from "@/components/dashboard/dashboardView";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

import { type FollowUpsQuery, STATUS_OPTIONS, WHEN_OPTIONS, whenLabel, WINDOW_DAYS } from "./followUpsQuery";

type Change = (next: Partial<FollowUpsQuery>, options?: { replace?: boolean }) => void;

/** To do / Done / All, each with how many match the other controls. */
export function StatusTabs({ status, data, onChange }: {
    status: FollowUpStatus;
    data: FollowUpListResponse | null;
    onChange: (status: FollowUpStatus) => void;
}) {
    const counts: Record<FollowUpStatus, number | null> = {
        open: data?.open_count ?? null,
        done: data?.done_count ?? null,
        all: data ? data.open_count + data.done_count : null,
    };
    return (
        <div role="tablist" aria-label="Follow-ups" className="-mb-px flex gap-1 overflow-x-auto px-3 [scrollbar-width:none] sm:gap-2 sm:px-4">
            {STATUS_OPTIONS.map((tab) => {
                const active = status === tab.value;
                const count = counts[tab.value];
                return (
                    <button
                        key={tab.value}
                        type="button"
                        role="tab"
                        aria-selected={active}
                        onClick={() => onChange(tab.value)}
                        className={cn(
                            "inline-flex min-h-12 flex-none items-center gap-1.5 border-b-2 px-2.5 text-[15px] outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-inset focus-visible:ring-ring/40 motion-reduce:transition-none",
                            active ? "border-brand font-semibold text-foreground" : "border-transparent text-ink-2 hover:text-foreground",
                        )}
                    >
                        {tab.label}
                        {count != null && (
                            <span
                                className={cn(
                                    "rounded-full px-1.5 text-[12.5px] font-semibold leading-5 tabular-nums",
                                    active && tab.value === "open" && count > 0 ? "bg-amber-dim text-amber" : active ? "bg-panel-2 text-ink-2" : "text-ink-3",
                                )}
                            >
                                {count.toLocaleString("en-IE")}
                            </span>
                        )}
                    </button>
                );
            })}
        </div>
    );
}

/** The search box and the date chip, as on Calls. */
export function FollowUpsFilterBar({ query, onChange }: { query: FollowUpsQuery; onChange: Change }) {
    const [text, setText] = useState(query.q);
    const typed = useRef(false);

    // Follow the URL (Back, Clear filters) unless the box is being typed in.
    useEffect(() => {
        if (!typed.current) setText(query.q);
    }, [query.q]);

    // Search as you type, after a pause; Enter searches at once.
    useEffect(() => {
        if (!typed.current) return;
        const timer = setTimeout(() => {
            typed.current = false;
            if (text.trim() !== query.q.trim()) onChange({ q: text }, { replace: true });
        }, 400);
        return () => clearTimeout(timer);
    }, [text, query.q, onChange]);

    const submit = (event: FormEvent) => {
        event.preventDefault();
        typed.current = false;
        if (text.trim() !== query.q.trim()) onChange({ q: text });
    };

    return (
        <div className="flex flex-col gap-2.5 px-4 py-3.5 sm:flex-row sm:items-center">
            <form role="search" aria-label="Search follow-ups" onSubmit={submit} className="relative min-w-0 sm:flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
                <input
                    type="search"
                    aria-label="Search names, numbers or what was said"
                    placeholder="Search names, numbers or what was said"
                    autoComplete="off"
                    value={text}
                    onChange={(event) => {
                        typed.current = true;
                        setText(event.target.value);
                    }}
                    className="h-10 w-full rounded-lg border border-line bg-panel pl-9 pr-9 text-[15px] text-foreground outline-none placeholder:text-ink-3 focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/30 [&::-webkit-search-cancel-button]:hidden"
                />
                {text && (
                    <button
                        type="button"
                        onClick={() => {
                            typed.current = false;
                            setText("");
                            onChange({ q: "" });
                        }}
                        aria-label="Clear the search"
                        className="absolute right-1 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-md text-ink-3 outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/40"
                    >
                        <X className="size-4" aria-hidden />
                    </button>
                )}
            </form>
            <div className="flex flex-wrap items-center gap-2">
                <DateChip query={query} onChange={onChange} />
            </div>
        </div>
    );
}

/** "Last 30 days" by default (the whole Follow-ups window); presets, or days picked by hand. */
function DateChip({ query, onChange }: { query: FollowUpsQuery; onChange: Change }) {
    const [open, setOpen] = useState(false);
    const [range, setRange] = useState<DateRange | undefined>();

    useEffect(() => {
        if (!open) return;
        const day = (value: string | null) => (value ? new Date(`${value}T00:00:00`) : undefined);
        setRange(query.when === "custom" ? { from: day(query.start), to: day(query.end ?? query.start) } : undefined);
    }, [open, query.when, query.start, query.end]);

    const choose = (next: Partial<FollowUpsQuery>) => {
        onChange(next);
        setOpen(false);
    };
    const today = new Date();
    const earliest = startOfDay(subDays(today, WINDOW_DAYS - 1));

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger className={cn(CHIP, query.when !== "30d" ? CHIP_ON : CHIP_OFF)}>
                <CalendarDays className="size-4" aria-hidden />
                <span className="sr-only">Dates: </span>
                {whenLabel(query)}
                <ChevronDown className="size-3.5" aria-hidden />
            </PopoverTrigger>
            <PopoverContent align="end" className="w-auto p-0">
                <div className="flex flex-col sm:flex-row">
                    <ul className="flex flex-row flex-wrap gap-1 border-b border-line-soft p-2 sm:w-40 sm:flex-col sm:border-b-0 sm:border-r">
                        {WHEN_OPTIONS.map((preset) => {
                            const active = query.when === preset.value;
                            return (
                                <li key={preset.value}>
                                    <button
                                        type="button"
                                        aria-pressed={active}
                                        onClick={() => choose({ when: preset.value, start: null, end: null })}
                                        className={cn(
                                            "flex min-h-10 w-full items-center justify-between gap-2 rounded-md px-2.5 text-left text-sm outline-none hover:bg-panel-2 focus-visible:ring-[3px] focus-visible:ring-ring/40 sm:min-h-8",
                                            active && "font-semibold text-brand",
                                        )}
                                    >
                                        {preset.label}
                                        {active && <Check className="size-3.5" aria-hidden />}
                                    </button>
                                </li>
                            );
                        })}
                    </ul>
                    <div className="p-1">
                        <p className="px-3 pt-2 text-[12.5px] text-ink-3">Or pick days (follow-ups go back 30 days)</p>
                        <Calendar
                            mode="range"
                            selected={range}
                            onSelect={setRange}
                            disabled={{ before: earliest, after: today }}
                            weekStartsOn={1}
                            numberOfMonths={1}
                        />
                        <div className="flex justify-end gap-2 px-3 pb-3">
                            <Button
                                size="sm"
                                disabled={!range?.from}
                                onClick={() =>
                                    range?.from &&
                                    choose({
                                        when: "custom",
                                        start: format(range.from, "yyyy-MM-dd"),
                                        end: format(range.to ?? range.from, "yyyy-MM-dd"),
                                    })
                                }
                            >
                                Show these days
                            </Button>
                        </div>
                    </div>
                </div>
            </PopoverContent>
        </Popover>
    );
}

/** One chip per kind, each with how many match the tab, dates and search. */
export function KindChips({ value, counts, onChange }: {
    value: FollowUpKind | null;
    counts: Record<string, number>;
    onChange: (kind: FollowUpKind | null) => void;
}) {
    const total = FOLLOW_UP_KINDS.reduce((sum, kind) => sum + (counts[kind] ?? 0), 0);
    const options: { value: FollowUpKind | null; label: string; count: number }[] = [
        { value: null, label: "Every kind", count: total },
        ...FOLLOW_UP_KINDS.map((kind) => ({ value: kind, label: FOLLOW_UP_WORDS[kind].filter, count: counts[kind] ?? 0 })),
    ];
    return (
        <div role="group" aria-label="Kind" className="-mt-1 flex gap-2 overflow-x-auto px-4 pb-3.5 pt-1 [scrollbar-width:none] sm:flex-wrap sm:overflow-visible">
            {options.map((option) => {
                const active = value === option.value;
                return (
                    <button
                        key={option.value ?? "all"}
                        type="button"
                        aria-pressed={active}
                        onClick={() => onChange(option.value)}
                        // A kind with nothing to show stays pressable when it's the one picked, so it can be cleared.
                        disabled={option.value !== null && option.count === 0 && !active}
                        className={cn(
                            "inline-flex h-9 flex-none items-center gap-2 whitespace-nowrap rounded-full border px-3.5 text-[14px] font-medium outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/40 disabled:opacity-45 motion-reduce:transition-none",
                            active ? CHIP_ON : CHIP_OFF,
                        )}
                    >
                        {option.value && (
                            <span aria-hidden className={cn("size-2 rounded-full", RULE_CLASSES[FOLLOW_UP_WORDS[option.value].tone])} />
                        )}
                        {option.label}
                        <span className="font-semibold tabular-nums">{option.count}</span>
                    </button>
                );
            })}
        </div>
    );
}
