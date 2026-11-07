import { Phone } from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import { ROW_LINK, ROW_LINK_CONTAINER } from "@/lib/rowLink";
import { cn } from "@/lib/utils";

import { callResultChip } from "./callOutcome";
import { callerLines, type CallRowProps, OutcomeChip, PlayButton } from "./CallsTable";
import { callSummary, formatCallWhen, formatLength, spokenLength } from "./callsView";

/**
 * The calls as a list of rows: on a phone, and beside the open call on a
 * computer. Each row reads top to bottom: who rang (and when), what
 * happened, then how it went. The caller is a real link stretched over the
 * row; the play button sits above it so it can be pressed on its own.
 */
export function CallCards({ runs, timezone, selectedId, hrefFor, onPlay, onOpen }: CallRowProps) {
    return (
        <ul className="flex flex-col divide-y divide-line-soft" aria-label="Calls">
            {runs.map((run) => {
                const { name, number } = callerLines(run);
                const outcome = callResultChip(run);
                const what = callSummary(run);
                const when = formatCallWhen(run.created_at, timezone);
                const selected = run.id === selectedId;
                return (
                    <li
                        key={run.id}
                        className={cn(
                            ROW_LINK_CONTAINER,
                            "flex items-start gap-3.5 px-4 py-4 transition-colors hover:bg-brand-dim/50 motion-reduce:transition-none sm:px-5",
                            selected && "bg-brand-dim shadow-[inset_3px_0_0_var(--brand)] hover:bg-brand-dim",
                        )}
                    >
                        {run.recording_url ? (
                            <PlayButton run={run} label={`${name}, ${when}`} onPlay={onPlay} className="mt-0.5 size-10" />
                        ) : (
                            // No recording: a plain marker keeps the rows lined up.
                            <span aria-hidden className="mt-0.5 grid size-10 flex-none place-items-center rounded-full bg-panel-2 text-ink-3">
                                <Phone className="size-4" />
                            </span>
                        )}
                        <div className="min-w-0 flex-1">
                            <div className="flex items-baseline justify-between gap-3">
                                <Link
                                    href={hrefFor(run)}
                                    scroll={false}
                                    onClick={() => onOpen?.(run)}
                                    aria-current={selected ? "true" : undefined}
                                    className={cn(ROW_LINK, "min-w-0 truncate text-[15.5px] font-semibold text-foreground")}
                                >
                                    {name}
                                    <span className="sr-only">, {when}</span>
                                </Link>
                                <span aria-hidden className="flex-none whitespace-nowrap text-[13px] tabular-nums text-ink-3">
                                    {when}
                                </span>
                            </div>
                            {what && <p className="mt-1 line-clamp-2 text-[14.5px] leading-snug text-ink-2">{what}</p>}
                            <div className="mt-2.5 flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
                                <OutcomeChip label={outcome.label} tone={outcome.tone} />
                                <span className="text-[13px] tabular-nums text-ink-3">
                                    <span aria-hidden>{formatLength(run.call_duration_seconds)}</span>
                                    <span className="sr-only">{spokenLength(run.call_duration_seconds)}</span>
                                    {number && <span> · {number}</span>}
                                </span>
                            </div>
                        </div>
                    </li>
                );
            })}
        </ul>
    );
}

export function CallCardsSkeleton({ rows = 5 }: { rows?: number }) {
    return (
        <div aria-hidden className="divide-y divide-line-soft">
            {Array.from({ length: rows }, (_, i) => (
                <div key={i} className="flex items-start gap-3.5 px-4 py-4 sm:px-5">
                    <Skeleton className="size-10 rounded-full" />
                    <div className="flex flex-1 flex-col gap-2">
                        <Skeleton className="h-4 w-2/3" />
                        <Skeleton className="h-3.5 w-5/6" />
                        <Skeleton className="h-6 w-28 rounded-full" />
                    </div>
                </div>
            ))}
        </div>
    );
}
