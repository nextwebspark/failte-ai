"use client";

import { EyeOff, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** The "Sample data" pill the design puts beside a page's title. */
export function SampleDataPill({ className }: { className?: string }) {
    return (
        <span
            className={cn(
                "inline-flex items-center whitespace-nowrap rounded-full bg-sky-dim px-2.5 py-[3px] text-[12px] font-semibold text-sky",
                className,
            )}
        >
            Sample data
        </span>
    );
}

/**
 * Says, for as long as it shows, that the calls on screen are made up, with
 * the way out (hide them) and the way to real ones (ring the agent).
 */
export function SampleBanner({
    text,
    onHide,
    action,
    className,
}: {
    text: string;
    onHide: () => void;
    /** The way to a first real call ("Try your agent"). */
    action?: ReactNode;
    className?: string;
}) {
    return (
        <section
            aria-label="Sample data"
            className={cn(
                "flex flex-col gap-3 rounded-[14px] border border-sky/30 border-l-[4px] border-l-sky bg-sky-dim px-[18px] py-3.5 sm:flex-row sm:items-center",
                className,
            )}
        >
            <Sparkles className="hidden size-5 flex-none text-sky sm:block" aria-hidden />
            <div className="min-w-0 flex-1">
                <p className="text-[14px] font-semibold text-foreground">Sample data</p>
                <p className="mt-0.5 text-[13px] text-ink-2">{text}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
                {action}
                <Button variant="outline" size="sm" onClick={onHide}>
                    <EyeOff aria-hidden />
                    Hide sample data
                </Button>
            </div>
        </section>
    );
}
