"use client";

import {
    ArrowLeft,
    Check,
    ChevronDown,
    Copy,
    Download,
    ExternalLink,
    FileText,
    MessageCircleQuestion,
    Phone,
    RefreshCw,
    Share2,
    X,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import {
    getUsageHistoryApiV1OrganizationsUsageRunsGet,
    getWorkflowRunApiV1WorkflowWorkflowIdRunsRunIdGet,
} from "@/client/sdk.gen";
import { SUPPORT_EMAIL } from "@/components/SupportLink";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { agentFactsHref } from "@/components/workflow/agentLinks";
import type { RealtimeFeedbackEvent } from "@/components/workflow/conversation";
import { conversationItemsFromRealtimeFeedbackEvents } from "@/components/workflow/conversation/adapters/fromRealtimeFeedback";
import { copyTextToClipboard } from "@/lib/clipboard";
import { downloadFile, getSignedUrl } from "@/lib/files";
import { cn } from "@/lib/utils";

import { callerLines, OutcomeChip } from "./CallsTable";
import {
    callDetails,
    callNumberOf,
    callOutcome,
    capturedValues,
    formatCallWhen,
    formatLengthWords,
    formatPhone,
    highlightParts,
    IN_PROGRESS_FOR_MS,
    isDialable,
} from "./callsView";
import { type CallRow, isSampleRun } from "./sampleRuns";
import { ShareRecordingDialog } from "./ShareRecordingDialog";

/** A recording usually lands within a minute or two of the call ending. */
const RECORDING_GRACE_MS = 15 * 60 * 1000;
/** Lines of the conversation shown before "Show the whole conversation". */
const FIRST_LINES = 4;

interface CallRecord {
    is_completed: boolean;
    recording_url: string | null;
    transcript_url: string | null;
    gathered_context: Record<string, unknown> | null;
    events: RealtimeFeedbackEvent[];
}

type Load<T> = { state: "loading" } | { state: "error" } | { state: "ready"; data: T };

export interface CallPanelProps {
    run: CallRow;
    timezone: string;
    /** Start the recording as soon as it loads (the row's play button). */
    autoplay: boolean;
    /** Move focus to the call (it was asked for, not shown by itself). */
    focusOnOpen: boolean;
    /** Full-screen on a phone, a drawer on a tablet, a column beside the list on a computer. */
    layout: "column" | "overlay";
    isPhone: boolean;
    fullPageHref: string;
    /** The search box's words, marked where they appear in what was said. */
    highlight?: string;
    onClose: () => void;
}

/** A spoken line of the call, oldest first. */
interface Line {
    id: string;
    who: "Agent" | "Caller";
    text: string;
}

function linesFrom(events: RealtimeFeedbackEvent[], toolResults: unknown): Line[] {
    return conversationItemsFromRealtimeFeedbackEvents(events, toolResults)
        .flatMap((item) =>
            item.kind === "message" && item.text.trim()
                ? [{ id: item.id, who: item.role === "assistant" ? "Agent" : "Caller", text: item.text.trim() } as Line]
                : [],
        );
}

/**
 * One call beside the list: how it ended, who rang, the recording, what the
 * agent took down and what was said. Technical detail stays folded away;
 * the full call page is one link away.
 */
export function CallPanel({ run, timezone, autoplay, focusOnOpen, layout, isPhone, fullPageHref, highlight = "", onClose }: CallPanelProps) {
    const headingRef = useRef<HTMLHeadingElement>(null);
    const [record, setRecord] = useState<Load<CallRecord>>({ state: "loading" });
    const [reload, setReload] = useState(0);
    const [timesBefore, setTimesBefore] = useState<number | null>(null);
    const [showAll, setShowAll] = useState(false);

    const { name, number } = callerLines(run);
    const outcome = callOutcome(run);
    const when = formatCallWhen(run.created_at, timezone);
    const rawNumber = callNumberOf(run);
    const isTest = run.mode === "webrtc" || run.mode === "smallwebrtc" || run.mode === "textchat";
    const sample = isSampleRun(run) ? run.sample ?? null : null;

    // Move focus to the call when it opens, so keyboard and screen-reader
    // users land on it (the list stays where it was).
    useEffect(() => {
        if (focusOnOpen) headingRef.current?.focus({ preventScroll: layout === "column" });
    }, [run.id, layout, focusOnOpen]);

    useEffect(() => {
        let cancelled = false;
        if (run.id < 0) {
            // A sample call is all in the browser: nothing to fetch.
            setRecord({
                state: "ready",
                data: { is_completed: true, recording_url: null, transcript_url: null, gathered_context: null, events: [] },
            });
            return;
        }
        setRecord({ state: "loading" });
        getWorkflowRunApiV1WorkflowWorkflowIdRunsRunIdGet({
            path: { workflow_id: run.workflow_id, run_id: run.id },
        })
            .then((response) => {
                if (cancelled) return;
                const data = response.data;
                if (!data) {
                    setRecord({ state: "error" });
                    return;
                }
                const logs = data.logs as { realtime_feedback_events?: RealtimeFeedbackEvent[] } | null | undefined;
                setRecord({
                    state: "ready",
                    data: {
                        is_completed: Boolean(data.is_completed),
                        recording_url: data.recording_url ?? null,
                        transcript_url: data.transcript_url ?? null,
                        gathered_context: (data.gathered_context as Record<string, unknown> | null) ?? null,
                        events: logs?.realtime_feedback_events ?? [],
                    },
                });
            })
            .catch(() => {
                if (!cancelled) setRecord({ state: "error" });
            });
        return () => {
            cancelled = true;
        };
    }, [run.workflow_id, run.id, reload]);

    // "Called 3 times before": one count from the same list, only for a real caller's number.
    useEffect(() => {
        let cancelled = false;
        setTimesBefore(null);
        if (run.call_type !== "inbound" || !isDialable(run.caller_number) || isTest || run.id < 0) return;
        const before = new Date(new Date(run.created_at).getTime() - 1).toISOString();
        getUsageHistoryApiV1OrganizationsUsageRunsGet({
            query: {
                page: 1,
                limit: 1,
                end_date: before,
                filters: JSON.stringify([
                    { attribute: "callerNumber", type: "text", value: { value: run.caller_number } },
                ]),
            },
        })
            .then((response) => {
                if (!cancelled && response.data) setTimesBefore(response.data.total_count);
            })
            .catch(() => undefined);
        return () => {
            cancelled = true;
        };
    }, [run.id, run.call_type, run.caller_number, run.created_at, isTest]);

    // Escape closes the drawer / full-screen view.
    useEffect(() => {
        if (layout !== "overlay") return;
        const onKey = (event: KeyboardEvent) => {
            if (event.key === "Escape") onClose();
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [layout, onClose]);

    const gathered = record.state === "ready" && !sample ? record.data.gathered_context : run.gathered_context ?? null;
    const details = useMemo(() => callDetails(gathered), [gathered]);
    const lines = useMemo(
        () =>
            sample
                ? sample.transcript.map(
                    (turn, index): Line => ({ id: `sample-${index}`, who: turn.role === "agent" ? "Agent" : "Caller", text: turn.text }),
                )
                : record.state === "ready"
                    ? linesFrom(record.data.events, record.data.gathered_context?.tool_results)
                    : [],
        [record, sample],
    );
    const searchWords = highlight.trim();
    const hits = useMemo(() => {
        const needle = searchWords.toLowerCase();
        return needle ? lines.filter((line) => line.text.toLowerCase().includes(needle)).length : 0;
    }, [lines, searchWords]);
    // A search hit further down opens the whole conversation, so it shows.
    useEffect(() => {
        const needle = searchWords.toLowerCase();
        if (needle && lines.slice(FIRST_LINES).some((line) => line.text.toLowerCase().includes(needle))) setShowAll(true);
    }, [lines, searchWords]);
    const summary = run.summary?.trim() || null;
    const reasonLabel = run.reason_label?.trim() || null;
    const unanswered = (run.unanswered_questions ?? []).filter((question) => question.trim());
    const captured = capturedValues(gathered).callback_number;
    const callbackNumber = [typeof captured === "string" ? captured.trim() : null, rawNumber].find(isDialable) ?? null;

    const stillGoing =
        record.state === "ready" &&
        !record.data.is_completed &&
        Date.now() - new Date(run.created_at).getTime() < IN_PROGRESS_FOR_MS;
    const chip = stillGoing ? { label: "Call in progress", tone: "live" as const } : outcome;
    const headingId = `call-${run.id}-title`;
    const visibleLines = showAll ? lines : lines.slice(0, FIRST_LINES);

    return (
        <aside
            aria-labelledby={headingId}
            role={layout === "overlay" ? "dialog" : undefined}
            aria-modal={layout === "overlay" ? true : undefined}
            className={cn(
                "flex flex-col bg-panel",
                layout === "column"
                    ? "sticky top-4 max-h-[calc(100dvh-6rem)] overflow-y-auto rounded-xl border border-line"
                    : "fixed inset-0 z-50 overflow-y-auto md:left-auto md:w-[460px] md:border-l md:border-line md:shadow-2xl",
            )}
        >
            {/* How it ended, when, and who rang. */}
            <div className="border-b border-line-soft px-5 pb-4 pt-4">
                {layout === "overlay" && isPhone ? (
                    <Button variant="ghost" className="-ml-2 mb-2 h-10 px-2" onClick={onClose}>
                        <ArrowLeft aria-hidden />
                        Back to calls
                    </Button>
                ) : null}
                <div className="flex items-start justify-between gap-3">
                    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5">
                        <OutcomeChip label={chip.label} tone={chip.tone} />
                        <span className="text-[13px] text-ink-3">
                            {when}
                            {!stillGoing && ` · ${formatLengthWords(run.call_duration_seconds)}`}
                        </span>
                    </div>
                    {!(layout === "overlay" && isPhone) && (
                        <Button
                            variant="ghost"
                            size="icon"
                            className="-mr-2 -mt-1 size-9 flex-none text-ink-3"
                            onClick={onClose}
                            aria-label="Close this call"
                        >
                            <X aria-hidden />
                        </Button>
                    )}
                </div>
                <h2
                    id={headingId}
                    ref={headingRef}
                    tabIndex={-1}
                    className="mt-2 truncate text-xl font-bold tracking-[-0.01em] text-foreground outline-none"
                >
                    {name}
                </h2>
                <p className="mt-0.5 text-[13.5px] text-ink-3">
                    {number ? <span className="tabular-nums">{number}</span> : !isTest && <span>Number not known</span>}
                    {timesBefore !== null && timesBefore > 0 && (
                        <span>
                            {number ? " · " : ""}called {timesBefore === 1 ? "once" : `${timesBefore} times`} before
                        </span>
                    )}
                </p>
            </div>

            <div className="flex flex-col gap-6 px-5 py-5">
                <Recording
                    record={record}
                    stillGoing={stillGoing}
                    run={run}
                    autoplay={autoplay}
                    onRetry={() => setReload((n) => n + 1)}
                />

                {(summary || reasonLabel) && (
                    <section aria-labelledby={`${headingId}-summary`}>
                        <h3 id={`${headingId}-summary`} className="mb-2 text-[11.5px] font-semibold uppercase tracking-[0.08em] text-ink-3">
                            Summary
                        </h3>
                        {summary && <p className="text-[14.5px] leading-relaxed text-foreground">{summary}</p>}
                        {reasonLabel && (
                            <p className={cn("text-[13.5px] text-ink-2", summary && "mt-2")}>
                                <span className="text-ink-3">What they wanted:</span> {reasonLabel}
                            </p>
                        )}
                    </section>
                )}

                {unanswered.length > 0 && (
                    <section aria-labelledby={`${headingId}-unanswered`} className="rounded-xl border border-line bg-panel-2 px-4 py-3">
                        <h3 id={`${headingId}-unanswered`} className="flex items-center gap-1.5 text-[13.5px] font-semibold text-foreground">
                            <MessageCircleQuestion className="size-4 text-ink-2" aria-hidden />
                            Your agent couldn&apos;t answer
                        </h3>
                        <ul className="mt-1.5 list-disc pl-5 text-[13.5px] text-foreground">
                            {unanswered.map((question, index) => (
                                <li key={index}>{question}</li>
                            ))}
                        </ul>
                        {sample ? (
                            <p className="mt-2 text-[12.5px] text-ink-3">
                                On a real call, this links to What your agent knows, where you add the answer.
                            </p>
                        ) : (
                            <Link
                                href={agentFactsHref(run.workflow_id)}
                                className="mt-2 inline-flex min-h-10 items-center rounded-sm text-sm font-semibold text-brand outline-none hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/40 sm:min-h-0"
                            >
                                Add the answer in What your agent knows
                            </Link>
                        )}
                    </section>
                )}

                {details.length > 0 && (
                    <section aria-labelledby={`${headingId}-details`}>
                        <h3 id={`${headingId}-details`} className="mb-2.5 text-[11.5px] font-semibold uppercase tracking-[0.08em] text-ink-3">
                            Details your agent took
                        </h3>
                        <dl className="grid grid-cols-2 gap-2">
                            {details.map((detail) => (
                                <div
                                    key={detail.key}
                                    className={cn(
                                        "min-w-0 rounded-lg border border-line px-3 py-2.5",
                                        detail.value.length > 28 && "col-span-2",
                                    )}
                                >
                                    <dt className="text-[12px] text-ink-3">{detail.label}</dt>
                                    <dd className="mt-0.5 break-words font-semibold text-foreground">{detail.value}</dd>
                                </div>
                            ))}
                        </dl>
                    </section>
                )}

                <section aria-labelledby={`${headingId}-said`}>
                    <h3 id={`${headingId}-said`} className="mb-2.5 text-[11.5px] font-semibold uppercase tracking-[0.08em] text-ink-3">
                        What was said
                    </h3>
                    {searchWords && lines.length > 0 && (
                        <p className="mb-2 text-[12.5px] text-ink-3" role="status">
                            {hits === 0
                                ? `“${searchWords}” isn't in what was said; it matched the caller or the summary.`
                                : `“${searchWords}” is marked in ${hits === 1 ? "1 line" : `${hits} lines`}.`}
                        </p>
                    )}
                    {record.state === "loading" ? (
                        <div className="flex flex-col gap-2" aria-label="Loading what was said">
                            <Skeleton className="h-14 w-4/5 rounded-xl" />
                            <Skeleton className="ml-auto h-12 w-3/4 rounded-xl" />
                        </div>
                    ) : record.state === "error" ? (
                        <p className="text-sm text-ink-3">We couldn&apos;t load this call. Try again in a moment.</p>
                    ) : stillGoing && lines.length === 0 ? (
                        <p className="text-sm text-ink-3">What was said shows here once the call ends.</p>
                    ) : lines.length > 0 ? (
                        <>
                            <ol className="flex flex-col gap-2">
                                {visibleLines.map((line) => (
                                    <li
                                        key={line.id}
                                        className={cn(
                                            "max-w-[88%] rounded-xl px-3 py-2 text-[13.5px] leading-relaxed",
                                            line.who === "Agent"
                                                ? "self-start bg-panel-2 text-foreground"
                                                : "self-end bg-sky-dim text-foreground",
                                        )}
                                    >
                                        <span className="block text-[12px] font-medium text-ink-3">{line.who}</span>
                                        <Highlighted text={line.text} words={searchWords} />
                                    </li>
                                ))}
                            </ol>
                            {lines.length > FIRST_LINES && (
                                <button
                                    type="button"
                                    onClick={() => setShowAll((open) => !open)}
                                    aria-expanded={showAll}
                                    className="mt-2 min-h-10 rounded-sm text-sm font-semibold text-brand outline-none hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/40 sm:min-h-0"
                                >
                                    {showAll ? "Show less" : "Show the whole conversation"}
                                </button>
                            )}
                        </>
                    ) : record.data.transcript_url ? (
                        <Button
                            variant="outline"
                            className="h-10 sm:h-9"
                            onClick={() => downloadFile(record.data.transcript_url)}
                        >
                            <FileText aria-hidden />
                            Open the written transcript
                        </Button>
                    ) : (
                        <p className="text-sm text-ink-3">Nothing was said on this call.</p>
                    )}
                </section>

                {sample ? (
                    <div className="flex flex-col gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                            <Button className="h-10 sm:h-9" disabled aria-describedby={`${headingId}-sample-note`}>
                                <Phone aria-hidden />
                                Call back
                            </Button>
                            <Button variant="outline" className="h-10 sm:h-9" disabled aria-describedby={`${headingId}-sample-note`}>
                                <Share2 aria-hidden />
                                Share recording
                            </Button>
                            <Button variant="outline" className="h-10 sm:h-9" disabled aria-describedby={`${headingId}-sample-note`}>
                                <Download aria-hidden />
                                Download recording
                            </Button>
                        </div>
                        <p id={`${headingId}-sample-note`} className="text-[12.5px] text-ink-3">
                            This is a sample call, so there&apos;s nobody to ring back and no recording to share or download.
                        </p>
                    </div>
                ) : (
                <div className="flex flex-wrap items-center gap-2">
                    {callbackNumber && !isTest && (
                        <CallBack number={callbackNumber} isPhone={isPhone} />
                    )}
                    {record.state === "ready" && record.data.recording_url && (
                        <ShareRecordingDialog runId={run.id} timezone={timezone} />
                    )}
                    {record.state === "ready" && record.data.recording_url && (
                        <Button
                            variant="outline"
                            className="h-10 sm:h-9"
                            onClick={() => downloadFile(record.data.recording_url)}
                        >
                            <Download aria-hidden />
                            Download recording
                        </Button>
                    )}
                    <a
                        href={`mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent(`Problem with call ${run.id}`)}`}
                        className="inline-flex min-h-10 items-center rounded-md px-2 text-sm font-medium text-ink-2 outline-none hover:text-foreground hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/40 sm:min-h-9"
                    >
                        Report a problem
                    </a>
                </div>
                )}

                <details className="group rounded-lg border border-line-soft">
                    <summary className="flex min-h-10 cursor-pointer list-none items-center justify-between gap-3 rounded-lg px-3 py-2 text-[13.5px] font-semibold text-ink-2 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40 [&::-webkit-details-marker]:hidden">
                        Technical details
                        <ChevronDown className="size-4 text-ink-3 transition-transform group-open:rotate-180 motion-reduce:transition-none" aria-hidden />
                    </summary>
                    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 border-t border-line-soft px-3 py-3 text-[13px]">
                        <dt className="text-ink-3">Agent</dt>
                        <dd className="min-w-0 truncate">{run.workflow_name || "Not known"}</dd>
                        <dt className="text-ink-3">Call ID</dt>
                        <dd className="tabular-nums">{run.id}</dd>
                        <dt className="text-ink-3">Kind</dt>
                        <dd>{callKind(run)}</dd>
                        {typeof run.charge_eur === "number" && (
                            <>
                                <dt className="text-ink-3">Charged</dt>
                                <dd className="tabular-nums">
                                    {new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR", maximumFractionDigits: 4 }).format(run.charge_eur)}
                                </dd>
                            </>
                        )}
                    </dl>
                    <div className="border-t border-line-soft px-3 py-2.5">
                        <Link
                            href={fullPageHref}
                            className="inline-flex min-h-10 items-center gap-1.5 rounded-sm text-sm font-semibold text-brand outline-none hover:underline focus-visible:ring-[3px] focus-visible:ring-ring/40 sm:min-h-0"
                        >
                            <ExternalLink className="size-4" aria-hidden />
                            Open full page
                        </Link>
                        <p className="mt-0.5 text-[12.5px] text-ink-3">The step-by-step record, for whoever set up your agent.</p>
                    </div>
                </details>
            </div>
        </aside>
    );
}

/** A line of what was said, with the search words marked (not by colour alone: bold and underlined). */
function Highlighted({ text, words }: { text: string; words: string }) {
    return (
        <>
            {highlightParts(text, words).map((part, index) =>
                part.hit ? (
                    <mark
                        key={index}
                        className="rounded-[3px] bg-amber-dim px-0.5 font-semibold text-foreground underline decoration-amber decoration-2 underline-offset-2"
                    >
                        {part.text}
                    </mark>
                ) : (
                    <span key={index}>{part.text}</span>
                ),
            )}
        </>
    );
}

function callKind(run: CallRow): string {
    if (run.mode === "textchat") return "Text chat (test)";
    if (run.mode === "webrtc" || run.mode === "smallwebrtc") return "Call from the browser (test)";
    return run.call_type === "inbound" ? "Phone call in" : "Phone call out";
}

/** The recording, or a plain word on why there isn't one. */
function Recording({ record, stillGoing, run, autoplay, onRetry }: {
    record: Load<CallRecord>;
    stillGoing: boolean;
    run: CallRow;
    autoplay: boolean;
    onRetry: () => void;
}) {
    const audioRef = useRef<HTMLAudioElement>(null);
    const [src, setSrc] = useState<Load<string> | null>(null);
    const key = record.state === "ready" ? record.data.recording_url : null;

    useEffect(() => {
        let cancelled = false;
        if (!key) {
            setSrc(null);
            return;
        }
        setSrc({ state: "loading" });
        getSignedUrl(key, true)
            .then((url) => {
                if (!cancelled) setSrc(url ? { state: "ready", data: url } : { state: "error" });
            })
            .catch(() => {
                if (!cancelled) setSrc({ state: "error" });
            });
        return () => {
            cancelled = true;
        };
    }, [key]);

    useEffect(() => {
        if (autoplay && src?.state === "ready") {
            audioRef.current?.play().catch(() => undefined);
        }
    }, [autoplay, src]);

    if (run.id < 0) {
        return <Notice>Sample call, no recording. Real calls play here.</Notice>;
    }
    if (record.state === "loading" || src?.state === "loading") {
        return <Skeleton className="h-14 w-full rounded-xl" aria-label="Loading the recording" />;
    }
    if (record.state === "error") {
        return (
            <Notice>
                We couldn&apos;t load this call.
                <RetryButton onClick={onRetry} />
            </Notice>
        );
    }
    if (stillGoing) {
        return (
            <Notice tone="live">
                This call is still going on. The recording and what was said appear here when it ends.
                <RetryButton onClick={onRetry} label="Check again" />
            </Notice>
        );
    }
    if (src?.state === "ready") {
        return (
            <div className="rounded-xl border border-line-soft bg-panel-2 p-1.5">
                {/* The browser's own player, told the page's theme so its controls are dark on dark. */}
                <audio
                    ref={audioRef}
                    controls
                    preload="metadata"
                    src={src.data}
                    className="block h-11 w-full rounded-lg [color-scheme:light] dark:[color-scheme:dark]"
                    aria-label={`Recording of the call, ${formatLengthWords(run.call_duration_seconds)}`}
                />
            </div>
        );
    }
    if (src?.state === "error") {
        return (
            <Notice>
                We couldn&apos;t load the recording.
                <RetryButton onClick={onRetry} />
            </Notice>
        );
    }
    if (run.mode === "textchat") return null;
    const ended = new Date(run.created_at).getTime() + run.call_duration_seconds * 1000;
    if (Date.now() - ended < RECORDING_GRACE_MS) {
        return (
            <Notice>
                The recording isn&apos;t ready yet. It usually appears a minute or two after the call ends.
                <RetryButton onClick={onRetry} label="Check again" />
            </Notice>
        );
    }
    return <Notice>No recording was kept for this call.</Notice>;
}

function Notice({ children, tone }: { children: React.ReactNode; tone?: "live" }) {
    return (
        <div
            role="status"
            className={cn(
                "flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-xl px-4 py-3 text-[13.5px]",
                tone === "live" ? "bg-live-dim text-foreground" : "bg-panel-2 text-ink-2",
            )}
        >
            {children}
        </div>
    );
}

function RetryButton({ onClick, label = "Try again" }: { onClick: () => void; label?: string }) {
    return (
        <Button variant="outline" size="sm" className="h-10 bg-panel sm:h-8" onClick={onClick}>
            <RefreshCw aria-hidden />
            {label}
        </Button>
    );
}

/** Call back: the dialler on a phone; on a computer, the number with a copy button. */
function CallBack({ number, isPhone }: { number: string; isPhone: boolean }) {
    const [copied, setCopied] = useState(false);
    const shown = formatPhone(number);
    const copy = useCallback(async () => {
        try {
            await copyTextToClipboard(number);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch {
            toast.error("Couldn't copy the number");
        }
    }, [number]);

    if (isPhone) {
        return (
            <Button asChild className="h-10">
                <a href={`tel:${number.replace(/[^\d+]/g, "")}`}>
                    <Phone aria-hidden />
                    Call back
                </a>
            </Button>
        );
    }
    return (
        <Popover>
            <PopoverTrigger asChild>
                <Button className="h-9">
                    <Phone aria-hidden />
                    Call back
                </Button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-auto">
                <p className="text-[12.5px] text-ink-3">Ring them back on</p>
                <p className="mt-0.5 text-lg font-semibold tabular-nums">{shown}</p>
                <Button variant="outline" size="sm" className="mt-3" onClick={copy}>
                    {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
                    {copied ? "Copied" : "Copy number"}
                </Button>
            </PopoverContent>
        </Popover>
    );
}
