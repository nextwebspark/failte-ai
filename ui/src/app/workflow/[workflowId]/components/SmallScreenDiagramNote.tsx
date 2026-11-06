"use client";

import { ArrowRight, Mic, Monitor } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { agentHomeHref } from "@/components/workflow/agentLinks";
import { useAgentShell } from "@/context/AgentShellContext";

/** Below Tailwind's `md`: a phone, where the flow diagram can't be used. */
export const SMALL_SCREEN_QUERY = "(max-width: 767px)";

/**
 * True on a phone-sized screen, false on anything bigger, null until the
 * browser has answered — so the page can wait rather than flash the diagram.
 */
export function useIsSmallScreen(): boolean | null {
    const [small, setSmall] = useState<boolean | null>(null);
    useEffect(() => {
        if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
            setSmall(false);
            return;
        }
        const query = window.matchMedia(SMALL_SCREEN_QUERY);
        const sync = () => setSmall(query.matches);
        sync();
        query.addEventListener?.("change", sync);
        return () => query.removeEventListener?.("change", sync);
    }, []);
    return small;
}

/**
 * What a phone shows instead of the conversation diagram: a friendly note,
 * the two things an owner can do well on a phone, and a way to see the
 * diagram anyway.
 */
export function SmallScreenDiagramNote({
    workflowId,
    onShowAnyway,
}: {
    workflowId: number;
    onShowAnyway: () => void;
}) {
    const { openTester } = useAgentShell();
    return (
        <div className="page-body">
            <section
                aria-labelledby="diagram-note-title"
                className="flex flex-col items-center rounded-xl border border-line bg-gradient-to-br from-brand-dim via-panel to-panel px-5 py-8 text-center"
            >
                <span className="grid size-11 place-items-center rounded-full bg-brand-dim text-brand" aria-hidden>
                    <Monitor className="size-5" />
                </span>
                <h2 id="diagram-note-title" className="mt-3 text-[17px] font-semibold text-foreground">
                    The conversation diagram is easier on a bigger screen
                </h2>
                <p className="mt-1.5 max-w-sm text-sm text-ink-2">
                    On your phone you can still change what your agent tells callers and talk to it to check how it
                    sounds.
                </p>
                <div className="mt-5 flex w-full max-w-xs flex-col gap-2.5">
                    <Button asChild size="lg" className="h-11">
                        <Link href={agentHomeHref(workflowId)}>
                            Go to Business facts
                            <ArrowRight className="size-4" aria-hidden />
                        </Link>
                    </Button>
                    <Button size="lg" variant="outline" className="h-11" onClick={openTester}>
                        <Mic className="size-4" aria-hidden />
                        Talk to your agent
                    </Button>
                    <Button variant="ghost" className="h-10 text-ink-2" onClick={onShowAnyway}>
                        Show the diagram anyway
                    </Button>
                </div>
            </section>
        </div>
    );
}

/** The conversation screen loading: its toolbar, then the canvas area. */
export function ConversationSkeleton() {
    return (
        <div className="flex h-full min-h-[60vh] flex-col" aria-busy="true" aria-label="Loading the conversation">
            <div className="flex items-center gap-2 border-b border-line-soft px-4 py-3">
                <Skeleton className="h-7 w-48" />
                <Skeleton className="h-7 w-28" />
                <Skeleton className="ml-auto h-8 w-24" />
                <Skeleton className="h-8 w-24" />
            </div>
            <div className="flex flex-1 items-center justify-center gap-6 p-8">
                <Skeleton className="h-28 w-48 rounded-xl" />
                <Skeleton className="h-28 w-48 rounded-xl" />
            </div>
        </div>
    );
}
