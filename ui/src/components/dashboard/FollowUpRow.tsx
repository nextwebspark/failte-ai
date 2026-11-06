"use client";

import { Check, Copy, Phone, Play, Undo2 } from "lucide-react";
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
export function CallBackButton({ number, label = "Call back" }: { number: string; label?: string }) {
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
            <Button asChild size="sm" className="md:hidden">
                <a href={telHref(number)}>
                    <Phone aria-hidden />
                    {label}
                </a>
            </Button>
            <span className="hidden h-8 items-center overflow-hidden rounded-md border border-brand/40 bg-brand-dim md:inline-flex">
                <span className="flex items-center gap-1.5 px-2.5 text-[12.5px] font-semibold tabular-nums text-brand">
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
    busy?: boolean;
}

/** One call that needs a person: a coloured rule, title and chip, what they wanted, and who/when. */
export function FollowUpRow({ item, timezone, now, returnTo, meta = "time", onMarkDone, onUndo, busy }: FollowUpRowProps) {
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
