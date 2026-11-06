"use client";

import { AlertCircle, RotateCw } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * The calm states every agent section shares — loading, empty and "couldn't
 * load" — in the same shape as the Calls page's empty state: a round icon,
 * one bold line, one helpful sentence, at most one action.
 *
 * Kept here, in the agent area, rather than in components/ui: the shared kit
 * belongs to the app shell.
 */

export function SectionMessage({
    icon,
    title,
    children,
    action,
    tone = "brand",
    className,
    role,
}: {
    icon: ReactNode;
    title: string;
    children?: ReactNode;
    action?: ReactNode;
    tone?: "brand" | "danger";
    className?: string;
    role?: "alert" | "status";
}) {
    return (
        <div
            role={role}
            className={cn(
                "flex flex-col items-center gap-2 rounded-xl border border-line bg-panel px-6 py-10 text-center",
                className,
            )}
        >
            <span
                aria-hidden
                className={cn(
                    "grid size-11 place-items-center rounded-full [&_svg]:size-5",
                    tone === "danger" ? "bg-danger-dim text-danger" : "bg-brand-dim text-brand",
                )}
            >
                {icon}
            </span>
            <p className="font-semibold text-foreground">{title}</p>
            {children ? <div className="max-w-sm text-sm text-ink-3">{children}</div> : null}
            {action ? <div className="mt-2">{action}</div> : null}
        </div>
    );
}

/** "Couldn't load" with a Try again button — never the raw error text. */
export function SectionError({
    title = "We couldn't load this just now",
    message = "Please check your connection and try again.",
    onRetry,
    className,
}: {
    title?: string;
    message?: string;
    onRetry?: () => void;
    className?: string;
}) {
    return (
        <SectionMessage
            role="alert"
            tone="danger"
            icon={<AlertCircle />}
            title={title}
            className={className}
            action={
                onRetry ? (
                    <Button variant="outline" onClick={onRetry} className="min-h-10">
                        <RotateCw className="size-4" aria-hidden />
                        Try again
                    </Button>
                ) : undefined
            }
        >
            {message}
        </SectionMessage>
    );
}

/**
 * A settings-style section loading: a heading line, then a few stacked
 * panels, so the page doesn't jump when the real one arrives.
 */
export function SectionSkeleton({ panels = 3, className }: { panels?: number; className?: string }) {
    return (
        <div className={cn("page-body max-w-4xl space-y-5", className)} aria-busy="true" aria-label="Loading">
            <div className="space-y-2">
                <Skeleton className="h-6 w-48" />
                <Skeleton className="h-4 w-full max-w-md" />
            </div>
            {Array.from({ length: panels }, (_, i) => (
                <Skeleton key={i} className="h-36 w-full rounded-xl" />
            ))}
        </div>
    );
}
