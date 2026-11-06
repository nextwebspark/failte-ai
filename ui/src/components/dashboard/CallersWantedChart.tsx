"use client";

import { useState } from "react";

import type { DashboardReason } from "@/client/types.gen";
import { cn } from "@/lib/utils";

/**
 * Colours follow the reason, never its rank: each template's reasons sit in
 * the same four slots (booking first, questions, changes, the business's own
 * fourth), Other is grey and "Not reviewed yet" a pale grey. Slots 1-4 of the
 * dataviz reference palette, validated for light (#ffffff) and dark
 * (#0e1013) surfaces with scripts/validate_palette.js: all checks pass; in
 * light mode aqua and yellow sit under 3:1, so the legend always prints each
 * reason's name, count and percent beside its swatch.
 */
type Colour = { stroke: string; swatch: string };
const SLOTS: Colour[] = [
    { stroke: "stroke-[#2a78d6] dark:stroke-[#3987e5]", swatch: "bg-[#2a78d6] dark:bg-[#3987e5]" },
    { stroke: "stroke-[#eb6834] dark:stroke-[#d95926]", swatch: "bg-[#eb6834] dark:bg-[#d95926]" },
    { stroke: "stroke-[#1baf7a] dark:stroke-[#199e70]", swatch: "bg-[#1baf7a] dark:bg-[#199e70]" },
    { stroke: "stroke-[#eda100] dark:stroke-[#c98500]", swatch: "bg-[#eda100] dark:bg-[#c98500]" },
];
const OTHER: Colour = { stroke: "stroke-[#9aa1ad] dark:stroke-[#6b7280]", swatch: "bg-[#9aa1ad] dark:bg-[#6b7280]" };
const NOT_REVIEWED: Colour = {
    stroke: "stroke-[#dfe3e9] dark:stroke-[#2b3038]",
    swatch: "bg-[#dfe3e9] ring-1 ring-inset ring-line dark:bg-[#2b3038]",
};

const KEY_SLOT: Record<string, number> = {
    reservations: 0,
    appointments: 0,
    new_job: 0,
    viewings: 0,
    questions: 1,
    property_questions: 1,
    changes: 2,
    existing_job: 2,
    takeaway: 3,
    urgent: 3,
    walk_ins: 3,
    selling: 3,
    speak_to_someone: 3,
};

/** The colour classes for each reason, by key (unknown keys take a free slot). */
export function reasonColours(reasons: Pick<DashboardReason, "key">[]): Record<string, Colour> {
    const colours: Record<string, Colour> = {};
    const used = new Set<number>();
    for (const r of reasons) {
        const slot = KEY_SLOT[r.key];
        if (slot !== undefined && !used.has(slot)) {
            colours[r.key] = SLOTS[slot];
            used.add(slot);
        }
    }
    for (const r of reasons) {
        if (colours[r.key]) continue;
        if (r.key === "other") colours[r.key] = OTHER;
        else if (r.key === "not_reviewed") colours[r.key] = NOT_REVIEWED;
        else {
            const free = SLOTS.findIndex((_, i) => !used.has(i));
            colours[r.key] = free >= 0 ? SLOTS[free] : OTHER;
            if (free >= 0) used.add(free);
        }
    }
    return colours;
}

const SIZE = 132;
const STROKE = 20;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
// The surface gap between segments, along the ring.
const GAP = 2;

/**
 * What callers wanted: a ring split by reason with the total in the middle,
 * and a legend that gives each reason's name, count and percent (so nothing
 * is told by colour alone). Hovering or focusing a segment or a legend row
 * shows that reason in the middle. The legend is the list screen readers read.
 */
export function CallersWantedChart({ reasons, caption }: { reasons: DashboardReason[]; caption: string }) {
    const [active, setActive] = useState<string | null>(null);
    const total = reasons.reduce((sum, r) => sum + r.count, 0);
    const colours = reasonColours(reasons);
    const shown = reasons.find((r) => r.key === active) ?? null;

    let offset = 0;
    const segments = reasons.map((reason) => {
        const length = total ? (reason.count / total) * CIRCUMFERENCE : 0;
        const segment = { reason, start: offset, length };
        offset += length;
        return segment;
    });
    const single = reasons.length === 1;

    return (
        <figure className="m-0 flex flex-col items-center gap-4 @sm:flex-row @sm:items-center @sm:gap-5">
            <div className="relative flex-none" style={{ width: SIZE, height: SIZE }} onMouseLeave={() => setActive(null)}>
                <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} aria-hidden className="-rotate-90">
                    {segments.map(({ reason, start, length }) => {
                        const drawn = single ? length : Math.max(0, length - GAP);
                        return (
                            <circle
                                key={reason.key}
                                cx={SIZE / 2}
                                cy={SIZE / 2}
                                r={RADIUS}
                                fill="none"
                                strokeWidth={active === reason.key ? STROKE + 4 : STROKE}
                                strokeDasharray={`${drawn} ${CIRCUMFERENCE - drawn}`}
                                strokeDashoffset={-start}
                                className={cn(
                                    "transition-[stroke-width,opacity]",
                                    colours[reason.key].stroke,
                                    active && active !== reason.key && "opacity-40",
                                )}
                                onMouseEnter={() => setActive(reason.key)}
                            />
                        );
                    })}
                </svg>
                <div className="pointer-events-none absolute inset-0 grid place-items-center text-center" >
                    {shown ? (
                        <div className="max-w-[92px]">
                            <div className="font-display text-[24px] font-semibold leading-none tabular-nums text-foreground">
                                {shown.count}
                            </div>
                            <div className="mt-1 text-[11px] leading-tight text-ink-2">
                                {shown.label} · {shown.percent}%
                            </div>
                        </div>
                    ) : (
                        <div>
                            <div className="font-display text-[30px] font-semibold leading-none tabular-nums text-foreground">{total}</div>
                            <div className="mt-1 text-[12px] text-ink-3">{total === 1 ? "call" : "calls"}</div>
                        </div>
                    )}
                </div>
            </div>
            <ul className="flex w-full min-w-0 flex-col gap-0.5" aria-label={caption}>
                {reasons.map((reason) => (
                    <li
                        key={reason.key}
                        tabIndex={0}
                        aria-label={`${reason.label}: ${reason.count} ${reason.count === 1 ? "call" : "calls"}, ${reason.percent}%`}
                        onMouseEnter={() => setActive(reason.key)}
                        onMouseLeave={() => setActive(null)}
                        onFocus={() => setActive(reason.key)}
                        onBlur={() => setActive(null)}
                        className={cn(
                            "grid grid-cols-[10px_minmax(0,1fr)_auto_3.25rem] items-center gap-x-2.5 rounded-md px-1.5 py-1.5 text-[13px] outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40",
                            active === reason.key && "bg-panel-2",
                        )}
                    >
                        <span className={cn("size-2.5 rounded-[3px]", colours[reason.key].swatch)} />
                        <span className={cn("min-w-0 leading-snug", reason.key === "not_reviewed" ? "text-ink-3" : "text-foreground")}>
                            {reason.label}
                        </span>
                        <span className="text-right font-semibold tabular-nums text-foreground">{reason.count}</span>
                        <span className="text-right tabular-nums text-ink-3">{reason.percent}%</span>
                    </li>
                ))}
            </ul>
            <figcaption className="sr-only">{caption}</figcaption>
        </figure>
    );
}
