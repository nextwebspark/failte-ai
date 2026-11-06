"use client";

import { useCallback, useEffect, useState } from "react";

import {
    countFollowUpsApiV1FollowUpsCountGet,
    getDashboardSummaryApiV1DashboardSummaryGet,
    listFollowUpsApiV1FollowUpsGet,
} from "@/client/sdk.gen";
import type { DashboardRange, DashboardSummaryResponse, FollowUpListResponse, FollowUpStatus } from "@/client/types.gen";
import { useAuth } from "@/lib/auth";

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

/** The follow-up list (to do or done), refreshed when one changes. */
export function useFollowUps(status: FollowUpStatus, workflowId?: number) {
    const [result, setResult] = useState<Loadable<FollowUpListResponse>>({ state: "loading" });
    const ready = useAuthReady();

    const load = useCallback(
        async (quiet = false) => {
            if (!ready) return;
            if (!quiet) setResult({ state: "loading" });
            try {
                const res = await listFollowUpsApiV1FollowUpsGet({
                    query: { status, workflow_id: workflowId ?? null },
                });
                setResult(res.data && !res.error ? { state: "ready", data: res.data } : { state: "error" });
            } catch {
                setResult({ state: "error" });
            }
        },
        [status, workflowId, ready],
    );

    useEffect(() => {
        void load();
    }, [load]);

    const reloadQuietly = useCallback(() => void load(true), [load]);
    useOnFollowUpsChanged(reloadQuietly);

    return { result, reload: () => void load(), reloadQuietly };
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
