"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";

import { busiestHour, hourLabel, hourWindow } from "./dashboardView";

/** A round top for the axis: 2, 4, 5, 10, 15, 20, … */
function niceMax(value: number): number {
    if (value <= 2) return 2;
    if (value <= 4) return 4;
    if (value <= 5) return 5;
    const step = value <= 20 ? 5 : value <= 50 ? 10 : 25;
    return Math.ceil(value / step) * step;
}

const CHART_HEIGHT = 196;

/**
 * Calls per hour of the day: one series, thin brand bars with rounded tops on
 * the baseline, a recessive grid, a tooltip on hover or focus, and the busiest
 * hour (only when it clearly stands out) in full brand with a label, the rest
 * a step lighter. Axis text is 12px ink; on a narrow card the hour labels go
 * every six hours instead of three. A table carries the same numbers for
 * screen readers. The business's open hours, when given, are a faint
 * neutral band behind the bars (explained by the legend under the chart).
 */
export function HourlyCallsChart({
    hours,
    caption,
    openRanges = [],
}: {
    hours: number[];
    caption: string;
    /** Open times to shade, in minutes after local midnight. */
    openRanges?: { start: number; end: number }[];
}) {
    const [active, setActive] = useState<number | null>(null);
    const { start, end } = hourWindow(hours, openRanges);
    const shown = Array.from({ length: end - start + 1 }, (_, i) => start + i);
    const top = niceMax(Math.max(0, ...hours));
    const peak = busiestHour(hours);
    const ticks = [top, top / 2, 0];

    return (
        <figure className="m-0">
            <div className="relative pl-8" style={{ height: CHART_HEIGHT + 26 }}>
                {/* Grid and y-axis labels */}
                <div className="absolute inset-x-0 top-0" style={{ height: CHART_HEIGHT }} aria-hidden>
                    {ticks.map((tick) => (
                        <div
                            key={tick}
                            className="absolute inset-x-0 flex items-center"
                            style={{ top: `${(1 - tick / top) * 100}%` }}
                        >
                            <span className="w-7 -translate-y-1/2 pr-2 text-right text-meta tabular-nums text-ink-3">
                                {Number.isInteger(tick) ? tick : ""}
                            </span>
                            <span className={cn("h-px flex-1 -translate-y-1/2", tick === 0 ? "bg-line" : "bg-line-soft")} />
                        </div>
                    ))}
                </div>

                {/* Bars, over the open-hours band */}
                <div className="relative flex items-end gap-[3px]" style={{ height: CHART_HEIGHT }} onMouseLeave={() => setActive(null)}>
                    {openRanges.map((range) => {
                        const from = Math.max(0, range.start / 60 - start);
                        const to = Math.min(shown.length, range.end / 60 - start);
                        if (to <= from) return null;
                        // Each hour's slot is (width + gap) / hours wide; the
                        // band's edges sit in the gaps between bars.
                        const unit = `(100% + 3px) / ${shown.length}`;
                        return (
                            <span
                                key={`${range.start}-${range.end}`}
                                className="pointer-events-none absolute inset-y-0 rounded-[4px] bg-ink-3/[0.08]"
                                style={{
                                    left: `max(0px, calc(${from} * ${unit} - 1.5px))`,
                                    width: `min(100%, calc(${to - from} * ${unit}))`,
                                }}
                                aria-hidden
                            />
                        );
                    })}
                    {shown.map((hour, index) => {
                        // Keep the tooltip inside the card near either edge.
                        const tipSide =
                            index < shown.length / 4 ? "left-0" : index > (shown.length * 3) / 4 ? "right-0" : "";
                        const count = hours[hour] ?? 0;
                        const height = count === 0 ? 0 : Math.max(3, (count / top) * CHART_HEIGHT);
                        const isActive = active === hour;
                        const tip = `${hourLabel(hour)}–${hourLabel((hour + 1) % 24)}: ${count} ${count === 1 ? "call" : "calls"}`;
                        return (
                            <div
                                key={hour}
                                className="relative flex h-full min-w-0 flex-1 cursor-default items-end justify-center outline-none"
                                tabIndex={0}
                                aria-label={tip}
                                onMouseEnter={() => setActive(hour)}
                                onFocus={() => setActive(hour)}
                                onBlur={() => setActive(null)}
                            >
                                {peak === hour && (
                                    <span
                                        className={cn(
                                            "pointer-events-none absolute whitespace-nowrap text-meta font-semibold text-foreground",
                                            isActive && "invisible",
                                        )}
                                        style={{ bottom: height + 5 }}
                                        aria-hidden
                                    >
                                        Busiest
                                    </span>
                                )}
                                <span
                                    className={cn(
                                        "block w-full max-w-[18px] rounded-t-[4px] transition-colors motion-reduce:transition-none",
                                        isActive || peak === hour ? "bg-brand" : "bg-brand/55",
                                    )}
                                    style={{ height }}
                                    aria-hidden
                                />
                                {isActive && (
                                    <span
                                        role="tooltip"
                                        className={cn(
                                            "pointer-events-none absolute z-10 whitespace-nowrap rounded-lg border border-line bg-popover px-2.5 py-1.5 text-caption font-medium tabular-nums text-foreground shadow-md",
                                            tipSide,
                                        )}
                                        style={{ bottom: height + 8 }}
                                    >
                                        {tip}
                                    </span>
                                )}
                            </div>
                        );
                    })}
                </div>

                {/* X-axis labels every third hour (every sixth on a narrow card) */}
                <div className="mt-2 flex gap-[3px]" aria-hidden>
                    {shown.map((hour) => (
                        <span key={hour} className="relative min-w-0 flex-1 text-center text-meta tabular-nums text-ink-3">
                            {hour % 3 === 0 ? (
                                <span
                                    className={cn(
                                        "absolute left-1/2 -translate-x-1/2",
                                        hour % 6 !== 0 && "hidden @md:inline",
                                    )}
                                >
                                    {hourLabel(hour)}
                                </span>
                            ) : null}
                        </span>
                    ))}
                </div>
            </div>
            <figcaption className="sr-only">{caption}</figcaption>
            <table className="sr-only">
                <caption>{caption}</caption>
                <thead>
                    <tr>
                        <th scope="col">Hour</th>
                        <th scope="col">Calls</th>
                    </tr>
                </thead>
                <tbody>
                    {shown.map((hour) => (
                        <tr key={hour}>
                            <td>{hourLabel(hour)}</td>
                            <td>{hours[hour] ?? 0}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </figure>
    );
}
