"use client";

import { Check, Copy, MessageSquarePlus, Phone, Play, Undo2 } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { toast } from "sonner";

import { formatPhone } from "@/app/usage/callsView";
import type { FollowUpItem } from "@/client/types.gen";
import { runDetailHref } from "@/components/layout/shellContext";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import {
    callBackNumber,
    callerWords,
    callLength,
    callWhen,
    CHIP_CLASSES,
    type ChipTone,
    FOLLOW_UP_WORDS,
    followUpDetail,
    followUpTitle,
    minutesSince,
    RULE_CLASSES,
    telHref,
    waitWords,
} from "./dashboardView";

export function Chip({ tone, children, className }: { tone: ChipTone; children: ReactNode; className?: string }) {
    return (
        <span
            className={cn(
                "inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[11.5px] font-semibold",
                CHIP_CLASSES[tone],
                className,
            )}
        >
            {children}
        </span>
    );
}

/**
 * Call back: on a phone, a button that opens the dialler; on a computer, the
 * number itself with a copy button (a computer can't ring it).
 */
export function CallBackButton({ number, label = "Call back", large = false }: { number: string; label?: string; large?: boolean }) {
    const copy = async () => {
        try {
            await navigator.clipboard.writeText(number);
            toast.success("Number copied");
        } catch {
            toast.error("Couldn't copy. Select the number instead.");
        }
    };
    return (
        <>
            <Button asChild size={large ? "default" : "sm"} className={cn("md:hidden", large && "h-10")}>
                <a href={telHref(number)}>
                    <Phone aria-hidden />
                    {label}
                </a>
            </Button>
            <span className={cn("hidden items-center overflow-hidden rounded-md border border-brand/40 bg-brand-dim md:inline-flex", large ? "h-9" : "h-8")}>
                <span className={cn("flex items-center gap-1.5 px-2.5 font-semibold tabular-nums text-brand", large ? "text-[14px]" : "text-[12.5px]")}>
                    <Phone className="size-3.5" aria-hidden />
                    <span className="sr-only">{label}: </span>
                    <span className="select-all">{formatPhone(number)}</span>
                </span>
                <button
                    type="button"
                    onClick={copy}
                    className="grid h-full place-items-center border-l border-brand/30 px-2 text-brand outline-none hover:bg-brand hover:text-white focus-visible:ring-[3px] focus-visible:ring-ring/40"
                    aria-label={`Copy ${number}`}
                    title="Copy number"
                >
                    <Copy className="size-3.5" aria-hidden />
                </button>
            </span>
        </>
    );
}

export function ListenLink({ item, returnTo }: { item: Pick<FollowUpItem, "workflow_id" | "run_id">; returnTo: string }) {
    return (
        <Button asChild variant="ghost" size="sm" className="text-ink-2">
            <Link href={runDetailHref(item.workflow_id, item.run_id, returnTo)}>
                <Play aria-hidden />
                Listen
            </Link>
        </Button>
    );
}

interface FollowUpRowProps {
    item: FollowUpItem;
    timezone?: string | null;
    now: Date;
    /** Where Listen comes back to. */
    returnTo: string;
    /** "waiting" shows how long it has waited (Follow-ups); "time" the call's time and length (Home). */
    meta?: "waiting" | "time";
    onMarkDone?: (item: FollowUpItem) => void;
    onUndo?: (item: FollowUpItem) => void;
    /** "Add answer" on a question the agent couldn't answer. */
    onAddAnswer?: (item: FollowUpItem) => void;
    busy?: boolean;
}

function OpenCallLink({ item, returnTo }: { item: Pick<FollowUpItem, "workflow_id" | "run_id">; returnTo: string }) {
    return (
        <Button asChild variant="ghost" size="sm" className="text-ink-2">
            <Link href={runDetailHref(item.workflow_id, item.run_id, returnTo)}>Open call</Link>
        </Button>
    );
}

/** One call that needs a person: a coloured rule, title and chip, what they wanted, and who/when. */
export function FollowUpRow({
    item,
    timezone,
    now,
    returnTo,
    meta = "time",
    onMarkDone,
    onUndo,
    onAddAnswer,
    busy,
}: FollowUpRowProps) {
    const words = FOLLOW_UP_WORDS[item.kind];
    const done = Boolean(item.done_at);
    const number = callBackNumber(item);
    const length = callLength(item.duration_seconds);
    const metaParts = [
        item.caller_number ? formatPhone(item.caller_number) : "Number withheld",
        callWhen(item.created_at, timezone, now),
        meta === "waiting" && !done ? `Waiting ${waitWords(minutesSince(item.created_at, now))}` : length,
        item.callback_number && item.callback_number !== item.caller_number ? `Asked to be rung on ${formatPhone(item.callback_number)}` : null,
    ].filter(Boolean);

    return (
        <li className="grid grid-cols-[4px_minmax(0,1fr)] gap-x-3 gap-y-2.5 border-t border-line-soft py-3 first:border-t-0 @xl:grid-cols-[4px_minmax(0,1fr)_auto] @xl:items-center">
            <span
                className={cn("row-span-2 self-stretch rounded @xl:row-span-1", done ? "bg-line" : RULE_CLASSES[words.tone])}
                aria-hidden
            />
            <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className={cn("text-[13.5px] font-semibold", done ? "text-ink-3 line-through" : "text-foreground")}>
                        {followUpTitle(item)}
                    </span>
                    {!done && <Chip tone={words.tone}>{words.chip}</Chip>}
                </div>
                <p className={cn("mt-0.5 text-[12.5px]", done ? "text-ink-3" : "text-ink-2")}>
                    {followUpDetail(item, timezone, now)}
                </p>
                <p className="mt-1 flex flex-wrap gap-x-3 text-[11.5px] tabular-nums text-ink-3">
                    {metaParts.map((p) => (
                        <span key={String(p)}>{p}</span>
                    ))}
                </p>
            </div>
            <div className="col-start-2 flex flex-wrap items-center gap-1.5 @xl:col-start-3 @xl:justify-end">
                {done ? (
                    <>
                        <span className="inline-flex items-center gap-1 text-[12.5px] text-brand">
                            <Check className="size-3.5" aria-hidden />
                            {[item.done_by, item.done_at ? callWhen(item.done_at, timezone, now) : null]
                                .filter(Boolean)
                                .join(", ")}
                        </span>
                        {onUndo && (
                            <Button variant="ghost" size="sm" onClick={() => onUndo(item)} disabled={busy}>
                                <Undo2 aria-hidden />
                                Undo
                            </Button>
                        )}
                    </>
                ) : item.kind === "unanswered_question" ? (
                    <>
                        {onAddAnswer && (
                            <Button size="sm" variant="soft" onClick={() => onAddAnswer(item)} disabled={busy}>
                                <MessageSquarePlus aria-hidden />
                                Add answer
                            </Button>
                        )}
                        {onMarkDone && (
                            <Button variant="ghost" size="sm" onClick={() => onMarkDone(item)} disabled={busy}>
                                Mark done
                            </Button>
                        )}
                    </>
                ) : item.kind === "time_was_full" ? (
                    <>
                        <OpenCallLink item={item} returnTo={returnTo} />
                        {onMarkDone && (
                            <Button variant="soft" size="sm" onClick={() => onMarkDone(item)} disabled={busy}>
                                Mark done
                            </Button>
                        )}
                    </>
                ) : (
                    <>
                        {item.has_recording && <ListenLink item={item} returnTo={returnTo} />}
                        {number && <CallBackButton number={number} />}
                        {onMarkDone && (
                            <Button variant="soft" size="sm" onClick={() => onMarkDone(item)} disabled={busy}>
                                Mark done
                            </Button>
                        )}
                    </>
                )}
            </div>
        </li>
    );
}

/** The circle on the left of a to-do: a ring in the kind's colour while it waits, a tick once done. */
function TodoMark({ tone, done }: { tone: ChipTone; done: boolean }) {
    return (
        <span
            aria-hidden
            className={cn(
                "mt-0.5 grid size-7 flex-none place-items-center rounded-full border-2",
                done ? "border-brand bg-brand text-white" : RING_CLASSES[tone],
            )}
        >
            {done && <Check className="size-4" strokeWidth={3} />}
        </span>
    );
}

const RING_CLASSES: Record<ChipTone, string> = {
    brand: "border-brand",
    sky: "border-sky",
    amber: "border-amber",
    danger: "border-danger",
    neutral: "border-line",
};

/** The heading of a to-do: who to ring when that's the job, else who rang (the chip says why). */
function todoTitle(item: FollowUpItem): string {
    return item.kind === "callback" || item.kind === "repeat_caller" ? followUpTitle(item) : callerWords(item);
}

/**
 * One follow-up on the Follow-ups page, as a to-do: a ring (a tick once
 * done), who and why, what they wanted, how long they've waited, and the
 * one thing to do about it.
 */
export function FollowUpTodo({
    item,
    timezone,
    now,
    returnTo,
    onMarkDone,
    onUndo,
    onAddAnswer,
    busy,
}: Omit<FollowUpRowProps, "meta">) {
    const words = FOLLOW_UP_WORDS[item.kind];
    const done = Boolean(item.done_at);
    const number = callBackNumber(item);
    const length = callLength(item.duration_seconds);
    const metaParts = [
        item.caller_number ? formatPhone(item.caller_number) : "Number withheld",
        callWhen(item.created_at, timezone, now),
        done ? length : `Waiting ${waitWords(minutesSince(item.created_at, now))}`,
        item.callback_number && item.callback_number !== item.caller_number ? `Asked to be rung on ${formatPhone(item.callback_number)}` : null,
    ].filter(Boolean);
    const doneWords = [item.done_by, item.done_at ? callWhen(item.done_at, timezone, now) : null].filter(Boolean).join(", ");
    const markDone = onMarkDone && (
        <Button variant="outline" onClick={() => onMarkDone(item)} disabled={busy} className="h-9 bg-panel">
            <Check aria-hidden />
            Mark done
        </Button>
    );

    return (
        <li
            className={cn(
                "grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-3 px-4 py-4 sm:px-5 @3xl:grid-cols-[auto_minmax(0,1fr)_auto] @3xl:items-center",
                done && "bg-panel-2/40",
            )}
        >
            <TodoMark tone={words.tone} done={done} />
            <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                    <h3 className={cn("text-[16px] font-semibold leading-snug", done ? "text-ink-3 line-through decoration-ink-3/60" : "text-foreground")}>
                        {todoTitle(item)}
                    </h3>
                    <Chip tone={done ? "neutral" : words.tone} className="px-2.5 text-[12.5px]">
                        {words.chip}
                    </Chip>
                </div>
                <p className={cn("mt-1 text-[14.5px] leading-snug", done ? "text-ink-3" : "text-ink-2")}>
                    {followUpDetail(item, timezone, now)}
                </p>
                <p className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[13px] tabular-nums text-ink-3">
                    {metaParts.map((p) => (
                        <span key={String(p)}>{p}</span>
                    ))}
                </p>
            </div>
            <div className="col-start-2 flex flex-wrap items-center gap-2 @3xl:col-start-3 @3xl:justify-end">
                {done ? (
                    <>
                        <span className="inline-flex items-center gap-1.5 text-[13.5px] font-medium text-brand">
                            <Check className="size-4" aria-hidden />
                            {doneWords ? `Done · ${doneWords}` : "Done"}
                        </span>
                        {onUndo && (
                            <Button variant="ghost" onClick={() => onUndo(item)} disabled={busy} className="h-9">
                                <Undo2 aria-hidden />
                                Undo
                            </Button>
                        )}
                    </>
                ) : item.kind === "unanswered_question" ? (
                    <>
                        {onAddAnswer && (
                            <Button onClick={() => onAddAnswer(item)} disabled={busy} className="h-9">
                                <MessageSquarePlus aria-hidden />
                                Add answer
                            </Button>
                        )}
                        {markDone}
                    </>
                ) : item.kind === "time_was_full" ? (
                    <>
                        <Button asChild variant="ghost" className="h-9 text-ink-2">
                            <Link href={runDetailHref(item.workflow_id, item.run_id, returnTo)}>Open call</Link>
                        </Button>
                        {number && <CallBackButton number={number} large />}
                        {markDone}
                    </>
                ) : (
                    <>
                        {number && <CallBackButton number={number} large />}
                        {item.has_recording && (
                            <Button asChild variant="ghost" className="h-9 text-ink-2">
                                <Link href={runDetailHref(item.workflow_id, item.run_id, returnTo)}>
                                    <Play aria-hidden />
                                    Listen
                                </Link>
                            </Button>
                        )}
                        {markDone}
                    </>
                )}
            </div>
        </li>
    );
}
