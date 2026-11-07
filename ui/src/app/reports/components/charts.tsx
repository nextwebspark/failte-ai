"use client";

import { type ReactNode, useState } from "react";

import { cn } from "@/lib/utils";

import { heatLevel, niceMax, shortHour, WEEKDAYS } from "../reportView";

const TOOLTIP =
    "pointer-events-none absolute z-20 whitespace-nowrap rounded-lg border border-line bg-popover px-2.5 py-1.5 text-caption font-medium tabular-nums text-foreground shadow-md";

/** Keep a tooltip inside the card near either edge. */
function tipSide(index: number, count: number): string {
    if (index < count / 4) return "left-0";
    if (index > (count * 3) / 4) return "right-0";
    return "left-1/2 -translate-x-1/2";
}

function Gridlines({ top, height }: { top: number; height: number }) {
    const ticks = [top, top / 2, 0];
    return (
        <div className="absolute inset-x-0 top-0" style={{ height }} aria-hidden>
            {ticks.map((tick) => (
                <div key={tick} className="absolute inset-x-0 flex items-center" style={{ top: `${(1 - tick / top) * 100}%` }}>
                    <span className="w-7 -translate-y-1/2 pr-2 text-right text-meta tabular-nums text-ink-3">
                        {Number.isInteger(tick) ? tick : ""}
                    </span>
                    <span className={cn("h-px flex-1 -translate-y-1/2", tick === 0 ? "bg-line" : "bg-line-soft")} />
                </div>
            ))}
        </div>
    );
}

export type Series = { key: string; label: string; swatch: string };

export type StackColumn = {
    key: string;
    label: string;
    /** Shown under the bar (every column, or fewer on long charts). */
    tick: string;
    counts: Record<string, number>;
    total: number;
};

/**
 * Stacked columns, one segment per series in its fixed order, with a 2px
 * surface gap between segments, the total over each column (when there's
 * room), a tooltip with the breakdown on hover or focus, and a legend. A
 * table carries the same numbers for screen readers.
 */
export function StackedColumns({
    series,
    columns,
    caption,
    height = 210,
}: {
    series: Series[];
    columns: StackColumn[];
    caption: string;
    height?: number;
}) {
    const [active, setActive] = useState<string | null>(null);
    const top = niceMax(Math.max(0, ...columns.map((c) => c.total)));
    const dense = columns.length > 14;
    const tickEvery = columns.length > 20 ? 5 : columns.length > 14 ? 3 : 1;
    return (
        <figure className="m-0">
            <div className="relative pl-8" style={{ height: height + 26 }}>
                <Gridlines top={top} height={height} />
                <div
                    className={cn("relative flex items-end", dense ? "gap-[2px]" : "gap-2")}
                    style={{ height }}
                    onMouseLeave={() => setActive(null)}
                >
                    {columns.map((column, index) => {
                        const h = column.total ? Math.max(3, (column.total / top) * height) : 0;
                        const isActive = active === column.key;
                        const breakdown = series.filter((s) => column.counts[s.key]);
                        const label = `${column.label}: ${column.total} ${column.total === 1 ? "call" : "calls"}${
                            breakdown.length ? ` (${breakdown.map((s) => `${s.label} ${column.counts[s.key]}`).join(", ")})` : ""
                        }`;
                        return (
                            <div
                                key={column.key}
                                tabIndex={0}
                                aria-label={label}
                                onMouseEnter={() => setActive(column.key)}
                                onFocus={() => setActive(column.key)}
                                onBlur={() => setActive(null)}
                                className="relative flex h-full min-w-0 flex-1 cursor-default flex-col items-center justify-end rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                            >
                                {!dense && column.total > 0 && (
                                    <span className="mb-1 text-meta font-semibold tabular-nums text-ink-2" aria-hidden>
                                        {column.total}
                                    </span>
                                )}
                                <div
                                    className={cn("flex w-full flex-col-reverse gap-[2px]", dense ? "max-w-[16px]" : "max-w-[44px]")}
                                    style={{ height: h }}
                                    aria-hidden
                                >
                                    {series.map((s, i) => {
                                        const n = column.counts[s.key] ?? 0;
                                        if (!n) return null;
                                        const last = !series.slice(i + 1).some((t) => column.counts[t.key]);
                                        return (
                                            <span
                                                key={s.key}
                                                className={cn(
                                                    "block w-full min-h-[2px]",
                                                    s.swatch,
                                                    last && "rounded-t-[4px]",
                                                    active && !isActive && "opacity-60",
                                                )}
                                                style={{ flexGrow: n, flexBasis: 0 }}
                                            />
                                        );
                                    })}
                                </div>
                                {isActive && (
                                    <div role="tooltip" className={cn(TOOLTIP, tipSide(index, columns.length))} style={{ bottom: h + 22 }}>
                                        <div className="font-semibold">{column.label}</div>
                                        {breakdown.length ? (
                                            breakdown.map((s) => (
                                                <div key={s.key} className="flex items-center gap-2 font-normal text-ink-2">
                                                    <span className={cn("size-2 rounded-[2px]", s.swatch)} />
                                                    {s.label}
                                                    <span className="ml-auto pl-3 font-semibold text-foreground">{column.counts[s.key]}</span>
                                                </div>
                                            ))
                                        ) : (
                                            <div className="font-normal text-ink-2">No calls</div>
                                        )}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
                <div className={cn("mt-2 flex", dense ? "gap-[2px]" : "gap-2")} aria-hidden>
                    {columns.map((column, index) => (
                        <span key={column.key} className="relative min-w-0 flex-1 text-center text-meta tabular-nums text-ink-3">
                            {index % tickEvery === 0 ? (
                                <span
                                    className={cn(
                                        "absolute left-1/2 -translate-x-1/2 whitespace-nowrap",
                                        index % (tickEvery * 2) !== 0 && "hidden @md:inline",
                                    )}
                                >
                                    {column.tick}
                                </span>
                            ) : null}
                        </span>
                    ))}
                </div>
            </div>
            <Legend series={series} />
            <figcaption className="sr-only">{caption}</figcaption>
            <div className="sr-only">
            <table>
                <caption>{caption}</caption>
                <thead>
                    <tr>
                        <th scope="col">When</th>
                        {series.map((s) => (
                            <th key={s.key} scope="col">
                                {s.label}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {columns.map((c) => (
                        <tr key={c.key}>
                            <td>{c.label}</td>
                            {series.map((s) => (
                                <td key={s.key}>{c.counts[s.key] ?? 0}</td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
            </div>
        </figure>
    );
}

export function Legend({ series }: { series: Series[] }) {
    if (series.length < 2) return null;
    return (
        <ul className="mt-4 flex flex-wrap gap-x-4 gap-y-1.5" aria-hidden>
            {series.map((s) => (
                <li key={s.key} className="flex items-center gap-1.5 text-caption text-ink-2">
                    <span className={cn("size-2.5 rounded-[3px]", s.swatch)} />
                    {s.label}
                </li>
            ))}
        </ul>
    );
}

// Sequential brand green, light to dark; level 0 is an empty cell.
const HEAT = ["bg-panel-2", "bg-brand/15", "bg-brand/30", "bg-brand/50", "bg-brand/75", "bg-brand"];

/**
 * Calls by weekday and hour: one hue, darker means busier, a tooltip per
 * cell, hour labels every few hours, and a table for screen readers.
 */
export function Heatmap({
    grid,
    firstHour,
    lastHour,
    max,
    caption,
}: {
    grid: number[][];
    firstHour: number;
    lastHour: number;
    max: number;
    caption: string;
}) {
    const [active, setActive] = useState<string | null>(null);
    const hours = Array.from({ length: lastHour - firstHour + 1 }, (_, i) => firstHour + i);
    const every = hours.length > 16 ? 4 : hours.length > 10 ? 2 : 1;
    return (
        <figure className="m-0">
            <div
                className="grid gap-[2px]"
                style={{ gridTemplateColumns: `2.25rem repeat(${hours.length}, minmax(0, 1fr))` }}
                onMouseLeave={() => setActive(null)}
            >
                {grid.map((row, day) => (
                    <HeatRow key={day} day={day} row={row} hours={hours} max={max} active={active} setActive={setActive} />
                ))}
                <span />
                {hours.map((hour, index) => (
                    <span key={hour} className="relative h-4 text-meta tabular-nums text-ink-3" aria-hidden>
                        {index % every === 0 ? (
                            <span className="absolute left-0 top-0.5 whitespace-nowrap">{shortHour(hour)}</span>
                        ) : null}
                    </span>
                ))}
            </div>
            <div className="mt-3 flex items-center gap-2 text-meta text-ink-3" aria-hidden>
                Fewer
                {HEAT.slice(1).map((shade) => (
                    <span key={shade} className={cn("size-3 rounded-[3px]", shade)} />
                ))}
                More
            </div>
            <figcaption className="sr-only">{caption}</figcaption>
            <div className="sr-only">
            <table>
                <caption>{caption}</caption>
                <thead>
                    <tr>
                        <th scope="col">Day</th>
                        {hours.map((h) => (
                            <th key={h} scope="col">
                                {shortHour(h)}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {grid.map((row, day) => (
                        <tr key={day}>
                            <th scope="row">{WEEKDAYS[day]}</th>
                            {hours.map((h) => (
                                <td key={h}>{row[h]}</td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
            </div>
        </figure>
    );
}

function HeatRow({
    day,
    row,
    hours,
    max,
    active,
    setActive,
}: {
    day: number;
    row: number[];
    hours: number[];
    max: number;
    active: string | null;
    setActive: (key: string | null) => void;
}) {
    return (
        <>
            <span className="self-center text-meta text-ink-3" aria-hidden>
                {WEEKDAYS[day].slice(0, 3)}
            </span>
            {hours.map((hour, index) => {
                const key = `${day}-${hour}`;
                const count = row[hour] ?? 0;
                const label = `${WEEKDAYS[day]} ${shortHour(hour)}–${shortHour(hour + 1)}: ${count} ${count === 1 ? "call" : "calls"}`;
                return (
                    <span
                        key={key}
                        tabIndex={-1}
                        aria-hidden
                        onMouseEnter={() => setActive(key)}
                        className={cn(
                            "relative h-6 rounded-[4px] sm:h-7",
                            HEAT[heatLevel(count, max)],
                            active === key && "ring-2 ring-foreground/60",
                        )}
                    >
                        {active === key && (
                            <span role="tooltip" className={cn(TOOLTIP, tipSide(index, hours.length), "bottom-full mb-1.5")}>
                                {label}
                            </span>
                        )}
                    </span>
                );
            })}
        </>
    );
}

export type Column = {
    key: string;
    tick: string;
    label: string;
    value: number;
    /** Drawn in full brand (the rest a step lighter). */
    strong?: boolean;
    /** Shown instead of a bar, e.g. "Closed". */
    note?: string;
};

/** Simple columns, one series: thin rounded bars on a baseline, a tooltip
 * per bar, optional values over the bars. */
export function Columns({
    columns,
    caption,
    unit,
    height = 170,
    showValues = false,
    tone = "bg-brand",
}: {
    columns: Column[];
    caption: string;
    unit: [string, string];
    height?: number;
    showValues?: boolean;
    tone?: string;
}) {
    const [active, setActive] = useState<string | null>(null);
    const top = niceMax(Math.max(0, ...columns.map((c) => c.value)));
    const dense = columns.length > 14;
    const tickEvery = columns.length > 16 ? 3 : 1;
    const words = (n: number) => `${n} ${n === 1 ? unit[0] : unit[1]}`;
    return (
        <figure className="m-0">
            <div className="relative pl-8" style={{ height: height + 26 }}>
                <Gridlines top={top} height={height} />
                <div className={cn("relative flex items-end", dense ? "gap-[2px]" : "gap-1.5")} style={{ height }} onMouseLeave={() => setActive(null)}>
                    {columns.map((column, index) => {
                        const h = column.value ? Math.max(3, (column.value / top) * height) : 0;
                        const label = `${column.label}: ${column.note ?? words(column.value)}`;
                        return (
                            <div
                                key={column.key}
                                tabIndex={0}
                                aria-label={label}
                                onMouseEnter={() => setActive(column.key)}
                                onFocus={() => setActive(column.key)}
                                onBlur={() => setActive(null)}
                                className="relative flex h-full min-w-0 flex-1 flex-col items-center justify-end rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                            >
                                {column.note && !column.value ? (
                                    <span className="mb-1 text-meta text-ink-3" aria-hidden>
                                        <span className="hidden @md:inline">{column.note}</span>
                                        <span className="@md:hidden">–</span>
                                    </span>
                                ) : showValues && column.value > 0 ? (
                                    <span className="mb-1 text-meta font-semibold tabular-nums text-ink-2" aria-hidden>
                                        {column.value}
                                    </span>
                                ) : null}
                                <span
                                    className={cn(
                                        "block w-full rounded-t-[4px]",
                                        dense ? "max-w-[14px]" : "max-w-[40px]",
                                        tone,
                                        !column.strong && active !== column.key && "opacity-55",
                                    )}
                                    style={{ height: h }}
                                    aria-hidden
                                />
                                {active === column.key && (
                                    <span role="tooltip" className={cn(TOOLTIP, tipSide(index, columns.length))} style={{ bottom: h + 22 }}>
                                        {label}
                                    </span>
                                )}
                            </div>
                        );
                    })}
                </div>
                <div className={cn("mt-2 flex", dense ? "gap-[2px]" : "gap-1.5")} aria-hidden>
                    {columns.map((column, index) => (
                        <span key={column.key} className="relative min-w-0 flex-1 text-center text-meta tabular-nums text-ink-3">
                            {index % tickEvery === 0 ? (
                                <span
                                    className={cn(
                                        "absolute left-1/2 -translate-x-1/2 whitespace-nowrap",
                                        index % (tickEvery * 2) !== 0 && "hidden @md:inline",
                                    )}
                                >
                                    {column.tick}
                                </span>
                            ) : null}
                        </span>
                    ))}
                </div>
            </div>
            <figcaption className="sr-only">{caption}</figcaption>
            <div className="sr-only">
            <table>
                <caption>{caption}</caption>
                <tbody>
                    {columns.map((c) => (
                        <tr key={c.key}>
                            <th scope="row">{c.label}</th>
                            <td>{c.note ?? c.value}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
            </div>
        </figure>
    );
}

/** A labelled thin bar with its count: "Allergies & diets ▬▬▬ 9". */
export function BarRow({
    label,
    value,
    max,
    swatch = "bg-brand",
    detail,
}: {
    label: ReactNode;
    value: number;
    max: number;
    swatch?: string;
    detail?: ReactNode;
}) {
    const width = max > 0 ? Math.max(value ? 3 : 0, (value / max) * 100) : 0;
    return (
        <li className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1">
            <span className="min-w-0 text-body text-foreground">{label}</span>
            <span className="text-right text-body font-semibold tabular-nums text-foreground">{value.toLocaleString("en-IE")}</span>
            <span className="col-span-2 h-1.5 overflow-hidden rounded-full bg-line-soft" aria-hidden>
                <span className={cn("block h-full rounded-full", swatch)} style={{ width: `${width}%` }} />
            </span>
            {detail ? <span className="col-span-2 text-caption text-ink-3">{detail}</span> : null}
        </li>
    );
}
