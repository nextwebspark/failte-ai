"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    countFollowUpsApiV1FollowUpsCountGet,
    getDashboardSummaryApiV1DashboardSummaryGet,
    listFollowUpsApiV1FollowUpsGet,
    markFollowUpDoneApiV1FollowUpsRunIdDonePost,
    undoFollowUpDoneApiV1FollowUpsRunIdDoneDelete,
} from "@/client/sdk.gen";
import type {
    DashboardRange,
    DashboardSummaryResponse,
    FollowUpItem,
    FollowUpKind,
    FollowUpListResponse,
    FollowUpStatus,
} from "@/client/types.gen";
import { useAuth } from "@/lib/auth";

import { followUpKey, markKind } from "./dashboardView";

export type Loadable<T> =
    | { state: "loading" }
    | { state: "error" }
    | { state: "ready"; data: T };

/** Fired after a follow-up is marked done or undone, so badges and lists refresh. */
const CHANGED = "lightmove:follow-ups-changed";

export function notifyFollowUpsChanged(): void {
    if (typeof window !== "undefined") window.dispatchEvent(new Event(CHANGED));
}

/** True once the API client can send the member's token. */
function useAuthReady(): boolean {
    const { user, loading } = useAuth();
    return !loading && Boolean(user);
}

function useOnFollowUpsChanged(reload: () => void) {
    useEffect(() => {
        window.addEventListener(CHANGED, reload);
        return () => window.removeEventListener(CHANGED, reload);
    }, [reload]);
}

/** Home's numbers for the range, from the dashboard endpoint. */
export function useDashboardSummary(range: DashboardRange, workflowId?: number) {
    const [result, setResult] = useState<Loadable<DashboardSummaryResponse>>({ state: "loading" });
    const ready = useAuthReady();

    const load = useCallback(async () => {
        if (!ready) return;
        setResult({ state: "loading" });
        try {
            const res = await getDashboardSummaryApiV1DashboardSummaryGet({
                query: { range, workflow_id: workflowId ?? null },
            });
            setResult(res.data && !res.error ? { state: "ready", data: res.data } : { state: "error" });
        } catch {
            setResult({ state: "error" });
        }
    }, [range, workflowId, ready]);

    useEffect(() => {
        void load();
    }, [load]);

    return { result, reload: load };
}

/** What the Follow-ups page narrows the list to; the API counts under the same. */
export interface FollowUpFilters {
    range?: DashboardRange | null;
    /** Days picked by hand, "yyyy-mm-dd" in the business's zone. */
    start_date?: string | null;
    end_date?: string | null;
    kind?: FollowUpKind | null;
    q?: string | null;
}

/** The follow-up list (to do, done or all), refreshed when one changes. */
export function useFollowUps(status: FollowUpStatus, workflowId?: number, filters?: FollowUpFilters) {
    const [result, setResult] = useState<Loadable<FollowUpListResponse>>({ state: "loading" });
    const ready = useAuthReady();
    const filterKey = JSON.stringify(filters ?? {});
    // Only the newest request may set the list (a quick typist sends several).
    const latest = useRef(0);
    const [updating, setUpdating] = useState(false);

    const load = useCallback(
        async (quiet = false) => {
            if (!ready) return;
            const request = ++latest.current;
            // A list already showing stays (marked as updating) while the
            // new one loads, so changing a filter doesn't blank the page.
            if (!quiet) setResult((current) => (current.state === "ready" ? current : { state: "loading" }));
            setUpdating(true);
            try {
                const narrow = JSON.parse(filterKey) as FollowUpFilters;
                const res = await listFollowUpsApiV1FollowUpsGet({
                    query: {
                        status,
                        workflow_id: workflowId ?? null,
                        ...(narrow.range && { range: narrow.range }),
                        ...(narrow.start_date && { start_date: narrow.start_date }),
                        ...(narrow.end_date && { end_date: narrow.end_date }),
                        ...(narrow.kind && { kind: narrow.kind }),
                        ...(narrow.q?.trim() && { q: narrow.q.trim() }),
                    },
                });
                if (request !== latest.current) return;
                setUpdating(false);
                setResult(res.data && !res.error ? { state: "ready", data: res.data } : { state: "error" });
            } catch {
                if (request === latest.current) {
                    setUpdating(false);
                    setResult({ state: "error" });
                }
            }
        },
        [status, workflowId, filterKey, ready],
    );

    useEffect(() => {
        void load();
    }, [load]);

    const reloadQuietly = useCallback(() => void load(true), [load]);
    useOnFollowUpsChanged(reloadQuietly);

    return { result, updating, reload: () => void load(), reloadQuietly };
}

/**
 * How many follow-ups are waiting: the number on the Follow-ups menu row.
 * Null until known (show no badge). Refreshes when one is marked done or
 * undone, and when the tab comes back into view.
 */
export function useOpenFollowUpCount(workflowId?: number): number | null {
    const [count, setCount] = useState<number | null>(null);
    const ready = useAuthReady();

    const load = useCallback(async () => {
        if (!ready) return;
        try {
            const res = await countFollowUpsApiV1FollowUpsCountGet({
                query: { workflow_id: workflowId ?? null },
            });
            if (res.data && !res.error) setCount(res.data.open);
        } catch {
            // Keep the last count; a badge is never worth an error.
        }
    }, [workflowId, ready]);

    useEffect(() => {
        void load();
        const onVisible = () => {
            if (document.visibilityState === "visible") void load();
        };
        document.addEventListener("visibilitychange", onVisible);
        return () => document.removeEventListener("visibilitychange", onVisible);
    }, [load]);

    const reload = useCallback(() => void load(), [load]);
    useOnFollowUpsChanged(reload);

    return count;
}

/**
 * Mark a follow-up done or put it back, with a toast (and Undo). `busy` is
 * the key (followUpKey) of the item being saved.
 */
export function useFollowUpMarking() {
    const [busy, setBusy] = useState<string | null>(null);

    const change = useCallback(async (item: FollowUpItem, done: boolean): Promise<void> => {
        setBusy(followUpKey(item));
        try {
            const kind = markKind(item.kind);
            const options = { path: { run_id: item.run_id }, query: kind ? { kind } : undefined };
            const res = done
                ? await markFollowUpDoneApiV1FollowUpsRunIdDonePost(options)
                : await undoFollowUpDoneApiV1FollowUpsRunIdDoneDelete(options);
            if (res.error) throw new Error("failed");
            notifyFollowUpsChanged();
            if (done) {
                toast.success("Marked done", {
                    action: { label: "Undo", onClick: () => void change(item, false) },
                });
            } else {
                toast.success("Back on the to-do list");
            }
        } catch {
            toast.error("Couldn't save that. Please try again.");
        } finally {
            setBusy(null);
        }
    }, []);

    return { busy, change };
}
