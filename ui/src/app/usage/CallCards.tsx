import { ChevronRight, Phone } from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import { ROW_LINK, ROW_LINK_CONTAINER } from "@/lib/rowLink";
import { cn } from "@/lib/utils";

import { callerLines, type CallRowProps, OutcomeChip, PlayButton } from "./CallsTable";
import { callOutcome, callSummary, formatCallWhen, formatLength, spokenLength } from "./callsView";

/**
 * The calls list on a phone: one card per call instead of a wide table. The
 * caller is a real link stretched over the card; the play button sits above
 * it so it can be tapped on its own.
 */
export function CallCards({ runs, timezone, selectedId, hrefFor, onPlay, onOpen }: CallRowProps) {
    return (
        <ul className="flex flex-col divide-y divide-line-soft" aria-label="Calls">
            {runs.map((run) => {
                const { name, number } = callerLines(run);
                const outcome = callOutcome(run);
                const what = callSummary(run);
                const when = formatCallWhen(run.created_at, timezone);
                const selected = run.id === selectedId;
                return (
                    <li
                        key={run.id}
                        className={cn(
                            ROW_LINK_CONTAINER,
                            "flex items-start gap-3 px-4 py-3.5 transition-colors hover:bg-brand-dim/60 motion-reduce:transition-none",
                            selected && "bg-brand-dim",
                        )}
                    >
                        {run.recording_url ? (
                            <PlayButton run={run} label={`${name}, ${when}`} onPlay={onPlay} className="mt-0.5 size-10" />
                        ) : (
                            // No recording: a plain marker keeps the cards lined up.
                            <span aria-hidden className="mt-0.5 grid size-10 flex-none place-items-center rounded-full bg-panel-2 text-ink-3">
                                <Phone className="size-4" />
                            </span>
                        )}
                        <div className="min-w-0 flex-1">
                            <div className="flex items-baseline gap-2">
                                <Link
                                    href={hrefFor(run)}
                                    scroll={false}
                                    onClick={() => onOpen?.(run)}
                                    aria-current={selected ? "true" : undefined}
                                    className={cn(ROW_LINK, "min-w-0 truncate text-[15px] font-semibold text-foreground")}
                                >
                                    {name}
                                    <span className="sr-only">, {when}</span>
                                </Link>
                            </div>
                            {number && <div className="truncate text-[13px] tabular-nums text-ink-3">{number}</div>}
                            {what && <p className="mt-1 line-clamp-2 text-sm text-ink-2">{what}</p>}
                            <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1">
                                <OutcomeChip label={outcome.label} tone={outcome.tone} />
                                <span className="text-[13px] tabular-nums text-ink-3">
                                    <span aria-hidden>{formatLength(run.call_duration_seconds)}</span>
                                    <span className="sr-only">{spokenLength(run.call_duration_seconds)}</span>
                                    <span aria-hidden> · {when}</span>
                                </span>
                            </div>
                        </div>
                        <ChevronRight className="mt-3 size-4 flex-none text-ink-3" aria-hidden />
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
                <div key={i} className="flex items-start gap-3 px-4 py-4">
                    <Skeleton className="size-10 rounded-full" />
                    <div className="flex flex-1 flex-col gap-2">
                        <Skeleton className="h-4 w-2/3" />
                        <Skeleton className="h-3 w-1/3" />
                        <Skeleton className="h-6 w-28 rounded-full" />
                    </div>
                </div>
            ))}
        </div>
    );
}
