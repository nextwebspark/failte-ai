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

const CHART_HEIGHT = 150;

/**
 * Calls per hour of the day: one series, thin brand bars with rounded tops on
 * the baseline, a recessive grid, a tooltip on hover or focus, and a label on
 * the busiest hour only when it clearly stands out. A table carries the same
 * numbers for screen readers.
 */
export function HourlyCallsChart({ hours, caption }: { hours: number[]; caption: string }) {
    const [active, setActive] = useState<number | null>(null);
    const { start, end } = hourWindow(hours);
    const shown = Array.from({ length: end - start + 1 }, (_, i) => start + i);
    const top = niceMax(Math.max(0, ...hours));
    const peak = busiestHour(hours);
    const ticks = [top, top / 2, 0];

    return (
        <figure className="m-0">
            <div className="relative pl-7" style={{ height: CHART_HEIGHT + 22 }}>
                {/* Grid and y-axis labels */}
                <div className="absolute inset-x-0 top-0" style={{ height: CHART_HEIGHT }} aria-hidden>
                    {ticks.map((tick) => (
                        <div
                            key={tick}
                            className="absolute inset-x-0 flex items-center"
                            style={{ top: `${(1 - tick / top) * 100}%` }}
                        >
                            <span className="w-6 -translate-y-1/2 pr-1.5 text-right text-[10.5px] tabular-nums text-ink-3">
                                {Number.isInteger(tick) ? tick : ""}
                            </span>
                            <span className={cn("h-px flex-1 -translate-y-1/2", tick === 0 ? "bg-line" : "bg-line-soft")} />
                        </div>
                    ))}
                </div>

                {/* Bars */}
                <div className="relative flex items-end gap-[2px]" style={{ height: CHART_HEIGHT }} onMouseLeave={() => setActive(null)}>
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
                                        className="pointer-events-none absolute whitespace-nowrap text-[10.5px] font-medium text-ink-2"
                                        style={{ bottom: height + 4 }}
                                        aria-hidden
                                    >
                                        Busiest
                                    </span>
                                )}
                                <span
                                    className={cn(
                                        "block w-full max-w-[14px] rounded-t-[4px] transition-colors",
                                        isActive ? "bg-brand" : "bg-brand/70",
                                    )}
                                    style={{ height }}
                                    aria-hidden
                                />
                                {isActive && (
                                    <span
                                        role="tooltip"
                                        className={cn(
                                            "pointer-events-none absolute z-10 whitespace-nowrap rounded-md border border-line bg-popover px-2 py-1 text-[11.5px] font-medium tabular-nums text-foreground shadow-md",
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

                {/* X-axis labels every third hour */}
                <div className="mt-1.5 flex gap-[2px]" aria-hidden>
                    {shown.map((hour) => (
                        <span key={hour} className="relative min-w-0 flex-1 text-center text-[10.5px] tabular-nums text-ink-3">
                            {hour % 3 === 0 ? <span className="absolute left-1/2 -translate-x-1/2">{hourLabel(hour)}</span> : null}
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
