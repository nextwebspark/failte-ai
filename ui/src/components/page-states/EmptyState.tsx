import type { LucideIcon } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

const TONES = {
    brand: "bg-brand-dim text-brand",
    amber: "bg-amber-dim text-amber",
} as const;

export interface EmptyStateProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
    icon: LucideIcon;
    /** One short, bold line. */
    title: React.ReactNode;
    /** One helpful sentence (the children). */
    children?: React.ReactNode;
    /** Usually one button or link: the next step. */
    action?: React.ReactNode;
    /** Brand for "nothing here yet", amber for "something's wrong, not your fault". */
    tone?: keyof typeof TONES;
    /** Heading level of the title, so it fits the page's outline. */
    as?: "h2" | "h3";
}

/**
 * The calm "nothing here" / "not available" block the Calls page started:
 * a round tinted icon, a bold one-line title, one sentence and one action.
 * Used for empty lists and for friendly load errors (never raw error text).
 */
export function EmptyState({
    icon: Icon,
    title,
    children,
    action,
    tone = "brand",
    as: Heading = "h2",
    className,
    ...props
}: EmptyStateProps) {
    return (
        <div
            className={cn(
                "flex flex-col items-center gap-2 rounded-xl border border-line bg-panel px-6 py-10 text-center",
                className,
            )}
            {...props}
        >
            <span className={cn("grid size-11 place-items-center rounded-full", TONES[tone])} aria-hidden>
                <Icon className="size-5" />
            </span>
            <Heading className="mt-1 text-base font-semibold text-foreground">{title}</Heading>
            {children ? <div className="max-w-md text-sm text-ink-3">{children}</div> : null}
            {action ? <div className="mt-3 flex flex-wrap justify-center gap-2">{action}</div> : null}
        </div>
    );
}
