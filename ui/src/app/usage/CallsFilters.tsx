"use client";

import { format } from "date-fns";
import { CalendarDays, Check, ChevronDown, Search, SlidersHorizontal, X } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import type { DateRange } from "react-day-picker";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

import {
    CALLS_TABS,
    type CallsQuery,
    type CallsTab,
    HANDLED_BY_OPTIONS,
    outcomeLabel,
    tabUsesDates,
    WHEN_PRESETS,
    whenLabel,
} from "./callsView";

const CHIP =
    "inline-flex h-10 items-center gap-1.5 rounded-full border px-3.5 text-sm font-medium outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/40 motion-reduce:transition-none sm:h-9";
const CHIP_OFF = "border-line bg-panel text-ink-2 hover:border-ink-3/40 hover:text-foreground";
const CHIP_ON = "border-brand/50 bg-brand-dim text-brand";

/** The tabs over the list, each with its real total (blank until counted). */
export function CallsTabs({ tab, counts, onChange, listId }: {
    tab: CallsTab;
    counts: Partial<Record<CallsTab, number>>;
    onChange: (tab: CallsTab) => void;
    listId: string;
}) {
    return (
        <div
            role="group"
            aria-label="Which calls"
            className="-mb-px flex gap-1 overflow-x-auto px-3 [scrollbar-width:none] sm:gap-2 sm:px-4"
        >
            {CALLS_TABS.map((option) => {
                const active = option.value === tab;
                const count = counts[option.value];
                return (
                    <button
                        key={option.value}
                        type="button"
                        aria-pressed={active}
                        aria-controls={listId}
                        aria-label={count === undefined ? option.label : `${option.label}, ${count.toLocaleString("en-IE")} ${count === 1 ? "call" : "calls"}`}
                        onClick={() => onChange(option.value)}
                        className={cn(
                            "inline-flex min-h-11 flex-none items-center gap-1.5 border-b-2 px-2.5 text-[14.5px] outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-inset focus-visible:ring-ring/40 motion-reduce:transition-none",
                            active
                                ? "border-brand font-semibold text-foreground"
                                : "border-transparent text-ink-2 hover:text-foreground",
                        )}
                    >
                        {option.label}
                        {count !== undefined && (
                            <span className={cn("tabular-nums", active ? "text-ink-2" : "text-ink-3")}>
                                {count.toLocaleString("en-IE")}
                            </span>
                        )}
                    </button>
                );
            })}
        </div>
    );
}

/**
 * One search box (names, numbers, the summary and what was said), the date,
 * outcome and "Who handled it" chips, and the quiet way into the expert
 * filters. On "Needs follow-up" the date chip gives way to Follow-ups' own
 * window, so the count matches that page.
 */
export function CallsFilterBar({
    query,
    outcomeCodes,
    expertCount,
    expertOpen,
    onChange,
    onToggleExpert,
}: {
    query: CallsQuery;
    outcomeCodes: string[];
    expertCount: number;
    expertOpen: boolean;
    onChange: (next: Partial<CallsQuery>, options?: { replace?: boolean }) => void;
    onToggleExpert: () => void;
}) {
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

    const outcomes = query.outcome && !outcomeCodes.includes(query.outcome)
        ? [...outcomeCodes, query.outcome]
        : outcomeCodes;
    const whoLabel = HANDLED_BY_OPTIONS.find((option) => option.value === query.who)?.label;

    return (
        <div className="flex flex-col gap-2.5 px-4 py-3.5 lg:flex-row lg:flex-wrap lg:items-center">
            <form role="search" aria-label="Search calls" onSubmit={submit} className="relative min-w-0 lg:min-w-[240px] lg:flex-1">
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
                    className="h-10 w-full rounded-lg border border-line bg-panel pl-9 pr-9 text-[15px] text-foreground outline-none placeholder:text-ink-3 focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/30 sm:text-sm [&::-webkit-search-cancel-button]:hidden"
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
                {tabUsesDates(query.tab) ? (
                    <DateChip query={query} onChange={onChange} />
                ) : (
                    <span className="inline-flex h-10 items-center gap-1.5 px-1 text-sm text-ink-3 sm:h-9">
                        <CalendarDays className="size-4" aria-hidden />
                        Last 30 days, as on Follow-ups
                    </span>
                )}

                <DropdownMenu>
                    <DropdownMenuTrigger className={cn(CHIP, query.outcome ? CHIP_ON : CHIP_OFF)}>
                        {query.outcome ? <span className="max-w-[160px] truncate">{outcomeLabel(query.outcome)}</span> : "Outcome"}
                        <ChevronDown className="size-3.5" aria-hidden />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start" className="max-h-80 overflow-y-auto">
                        <DropdownMenuRadioGroup
                            value={query.outcome ?? "any"}
                            onValueChange={(value) => onChange({ outcome: value === "any" ? null : value })}
                        >
                            <DropdownMenuRadioItem value="any">Any outcome</DropdownMenuRadioItem>
                            {outcomes.map((code) => (
                                <DropdownMenuRadioItem key={code} value={code}>{outcomeLabel(code)}</DropdownMenuRadioItem>
                            ))}
                        </DropdownMenuRadioGroup>
                    </DropdownMenuContent>
                </DropdownMenu>

                <DropdownMenu>
                    <DropdownMenuTrigger className={cn(CHIP, query.who ? CHIP_ON : CHIP_OFF)}>
                        {whoLabel ?? "Who handled it"}
                        <ChevronDown className="size-3.5" aria-hidden />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start">
                        <DropdownMenuRadioGroup
                            value={query.who ?? "anyone"}
                            onValueChange={(value) => onChange({ who: value === "anyone" ? null : (value as CallsQuery["who"]) })}
                        >
                            <DropdownMenuRadioItem value="anyone">Anyone</DropdownMenuRadioItem>
                            {HANDLED_BY_OPTIONS.map((option) => (
                                <DropdownMenuRadioItem key={option.value} value={option.value}>{option.label}</DropdownMenuRadioItem>
                            ))}
                        </DropdownMenuRadioGroup>
                    </DropdownMenuContent>
                </DropdownMenu>

                <button
                    type="button"
                    onClick={onToggleExpert}
                    aria-expanded={expertOpen}
                    aria-controls="calls-more-filters"
                    className="inline-flex h-10 items-center gap-1.5 rounded-md px-2 text-sm text-ink-3 outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/40 sm:h-9"
                >
                    <SlidersHorizontal className="size-3.5" aria-hidden />
                    More filters
                    {expertCount > 0 && (
                        <span className="rounded-full bg-brand px-1.5 text-[11px] font-semibold leading-[18px] text-white">
                            {expertCount}
                            <span className="sr-only"> on</span>
                        </span>
                    )}
                </button>
            </div>
        </div>
    );
}

/** "Last 7 days" by default; presets, or a range of days. */
function DateChip({ query, onChange }: {
    query: CallsQuery;
    onChange: (next: Partial<CallsQuery>) => void;
}) {
    const [open, setOpen] = useState(false);
    const [range, setRange] = useState<DateRange | undefined>();

    useEffect(() => {
        if (!open) return;
        const day = (value: string | null) => (value ? new Date(`${value}T00:00:00`) : undefined);
        setRange(query.when === "custom" ? { from: day(query.start), to: day(query.end ?? query.start) } : undefined);
    }, [open, query.when, query.start, query.end]);

    const choose = (next: Partial<CallsQuery>) => {
        onChange(next);
        setOpen(false);
    };

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger className={cn(CHIP, query.when !== "all" ? CHIP_ON : CHIP_OFF)}>
                <CalendarDays className="size-4" aria-hidden />
                <span className="sr-only">Dates: </span>
                {whenLabel(query)}
                <ChevronDown className="size-3.5" aria-hidden />
            </PopoverTrigger>
            <PopoverContent align="start" className="w-auto p-0">
                <div className="flex flex-col sm:flex-row">
                    <ul className="flex flex-row flex-wrap gap-1 border-b border-line-soft p-2 sm:w-40 sm:flex-col sm:border-b-0 sm:border-r">
                        {WHEN_PRESETS.map((preset) => {
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
                        <p className="px-3 pt-2 text-[12.5px] text-ink-3">Or pick days</p>
                        <Calendar
                            mode="range"
                            selected={range}
                            onSelect={setRange}
                            disabled={{ after: new Date() }}
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
