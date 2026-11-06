import { Play } from "lucide-react";
import Link from "next/link";

import type { WorkflowRunUsageResponse } from "@/client/types.gen";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ROW_LINK, ROW_LINK_CONTAINER } from "@/lib/rowLink";
import { cn } from "@/lib/utils";

import {
    callerNameOf,
    callNumberOf,
    callOutcome,
    formatCallWhen,
    formatLength,
    formatPhone,
    spokenLength,
    whatHappened,
} from "./callsView";

export interface CallRowProps {
    runs: WorkflowRunUsageResponse[];
    timezone: string;
    selectedId: number | null;
    hrefFor: (run: WorkflowRunUsageResponse) => string;
    onPlay: (run: WorkflowRunUsageResponse) => void;
    /** Told when a row's link is followed, so closing the call can go Back. */
    onOpen?: (run: WorkflowRunUsageResponse) => void;
}

/** "Declan Murphy" / "Unknown caller" / "Test call", and the number under it. */
export function callerLines(run: WorkflowRunUsageResponse): { name: string; number: string | null } {
    const name = callerNameOf(run.gathered_context);
    const number = callNumberOf(run);
    // Browser calls and text chats are someone trying the agent out.
    const fallback = run.mode === "textchat"
        ? "Test chat"
        : run.mode === "webrtc" || run.mode === "smallwebrtc"
            ? "Test call"
            : "Unknown caller";
    return {
        name: name ?? fallback,
        number: number ? formatPhone(number) : null,
    };
}

/** The round play button on a row: opens the call and starts its recording. */
export function PlayButton({ run, label, onPlay, className }: {
    run: WorkflowRunUsageResponse;
    label: string;
    onPlay: (run: WorkflowRunUsageResponse) => void;
    className?: string;
}) {
    if (!run.recording_url) {
        return <span className={cn("block size-8", className)} aria-hidden />;
    }
    return (
        <button
            type="button"
            onClick={() => onPlay(run)}
            aria-label={`Play the recording: ${label}`}
            className={cn(
                "relative z-10 grid size-8 place-items-center rounded-full bg-brand-dim text-brand outline-none transition-colors hover:bg-brand hover:text-white focus-visible:ring-[3px] focus-visible:ring-ring/40 motion-reduce:transition-none",
                className,
            )}
        >
            <Play className="size-3.5 fill-current" aria-hidden />
        </button>
    );
}

/**
 * The calls list on a computer. The caller's name is a real link stretched
 * over the row, so the whole row opens the call (click, Enter, or a new tab),
 * and the play button sits above it.
 */
export function CallsTable({ runs, timezone, selectedId, hrefFor, onPlay, onOpen }: CallRowProps) {
    // "What happened" is only what the agent took down; with nothing taken down
    // on this page the column would be empty, so it goes.
    const showWhat = runs.some((run) => whatHappened(run.gathered_context));
    return (
        <Table>
            <TableHeader className="bg-transparent">
                <TableRow className="hover:bg-transparent">
                    <TableHead className="w-12 pr-0"><span className="sr-only">Recording</span></TableHead>
                    <TableHead>Caller</TableHead>
                    {showWhat && <TableHead className="whitespace-nowrap">What happened</TableHead>}
                    <TableHead>Outcome</TableHead>
                    <TableHead>Length</TableHead>
                    <TableHead className="text-right">When</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {runs.map((run) => {
                    const { name, number } = callerLines(run);
                    const outcome = callOutcome(run);
                    const what = whatHappened(run.gathered_context);
                    const when = formatCallWhen(run.created_at, timezone);
                    const selected = run.id === selectedId;
                    return (
                        <TableRow
                            key={run.id}
                            className={cn(
                                ROW_LINK_CONTAINER,
                                "hover:bg-brand-dim/60",
                                selected && "bg-brand-dim shadow-[inset_3px_0_0_var(--brand)] hover:bg-brand-dim",
                            )}
                        >
                            <TableCell className="py-3 pr-0">
                                <PlayButton run={run} label={`${name}, ${when}`} onPlay={onPlay} />
                            </TableCell>
                            <TableCell className="max-w-[180px] py-3">
                                <Link
                                    href={hrefFor(run)}
                                    scroll={false}
                                    onClick={() => onOpen?.(run)}
                                    aria-current={selected ? "true" : undefined}
                                    className={cn(ROW_LINK, "block truncate font-semibold text-foreground")}
                                >
                                    {name}
                                    <span className="sr-only">, {when}</span>
                                </Link>
                                {number && <div className="truncate text-[13px] tabular-nums text-ink-3">{number}</div>}
                            </TableCell>
                            {showWhat && (
                                <TableCell className="py-3 text-ink-2">
                                    {what ? (
                                        <span className="line-clamp-2 min-w-[150px] whitespace-normal">{what}</span>
                                    ) : (
                                        <span className="text-ink-3">
                                            <span aria-hidden>–</span>
                                            <span className="sr-only">Nothing taken down</span>
                                        </span>
                                    )}
                                </TableCell>
                            )}
                            <TableCell className="py-3">
                                <OutcomeChip label={outcome.label} tone={outcome.tone} />
                            </TableCell>
                            <TableCell className="whitespace-nowrap py-3 tabular-nums">
                                <span aria-hidden>{formatLength(run.call_duration_seconds)}</span>
                                <span className="sr-only">{spokenLength(run.call_duration_seconds)}</span>
                            </TableCell>
                            <TableCell className="whitespace-nowrap py-3 text-right text-ink-3">{when}</TableCell>
                        </TableRow>
                    );
                })}
            </TableBody>
        </Table>
    );
}

/** The outcome as the shared status pill, in sentence case like the rest of the list. */
export function OutcomeChip({ label, tone, className }: {
    label: string;
    tone: React.ComponentProps<typeof StatusPill>["tone"];
    className?: string;
}) {
    return (
        <StatusPill
            tone={tone}
            className={cn(
                "whitespace-nowrap rounded-full px-2.5 py-1 text-[12px] font-semibold normal-case tracking-normal",
                tone === "mute" && "bg-panel-2 text-ink-2",
                className,
            )}
        >
            {label}
        </StatusPill>
    );
}

/** Placeholder rows while the list loads. */
export function CallsTableSkeleton({ rows = 6 }: { rows?: number }) {
    return (
        <div aria-hidden className="divide-y divide-line-soft">
            {Array.from({ length: rows }, (_, i) => (
                <div key={i} className="flex items-center gap-4 px-4 py-4">
                    <Skeleton className="size-8 rounded-full" />
                    <div className="flex w-[26%] flex-col gap-1.5">
                        <Skeleton className="h-4 w-3/4" />
                        <Skeleton className="h-3 w-1/2" />
                    </div>
                    <Skeleton className="h-4 flex-1" />
                    <Skeleton className="h-6 w-24 rounded-full" />
                    <Skeleton className="h-4 w-10" />
                    <Skeleton className="h-4 w-24" />
                </div>
            ))}
        </div>
    );
}
