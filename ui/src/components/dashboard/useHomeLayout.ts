"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    clearWorkspaceHomeLayoutApiV1DashboardLayoutWorkspaceDelete,
    getHomeLayoutApiV1DashboardLayoutGet,
    resetHomeLayoutApiV1DashboardLayoutDelete,
    saveHomeLayoutApiV1DashboardLayoutPut,
    saveWorkspaceHomeLayoutApiV1DashboardLayoutWorkspacePut,
} from "@/client/sdk.gen";
import type { HomeLayout, HomeLayoutResponse } from "@/client/types.gen";
import { useAuth } from "@/lib/auth";

import { EMPTY_LAYOUT, type Layout } from "./homeLayout";

export type HomeLayoutState = {
    /** Null while loading. If it can't be read, every card shows. */
    layout: Layout | null;
    source: HomeLayoutResponse["source"] | null;
    workspaceDefault: Layout | null;
    canSetWorkspaceDefault: boolean;
    /** Save the member's own layout (shown at once, saved on their account). */
    change: (next: Layout) => void;
    /** Forget the member's own layout. */
    reset: () => void;
    saveWorkspaceDefault: () => void;
    clearWorkspaceDefault: () => void;
};

function toLayout(layout: HomeLayout | null | undefined): Layout | null {
    return layout ? { hidden: layout.hidden ?? [], pinned: layout.pinned ?? [] } : null;
}

type Call = () => Promise<{ data?: HomeLayoutResponse; error?: unknown }>;

/** The member's Home layout, and ways to change it at each level they may. */
export function useHomeLayout(): HomeLayoutState {
    const { user, loading } = useAuth();
    const [data, setData] = useState<HomeLayoutResponse | null>(null);
    const [failed, setFailed] = useState(false);
    // Only the newest answer may set the layout.
    const latest = useRef(0);

    const ready = !loading && Boolean(user);
    // A different person (signing in as someone else) reads their own layout.
    const userId = user?.id;
    useEffect(() => {
        if (!ready) return;
        const request = ++latest.current;
        getHomeLayoutApiV1DashboardLayoutGet()
            .then((res) => {
                if (request !== latest.current) return;
                if (res.data) setData(res.data);
                else setFailed(true);
            })
            .catch(() => {
                if (request === latest.current) setFailed(true);
            });
    }, [ready, userId]);

    const send = useCallback(async (call: Call, failure: string, success?: string) => {
        const request = ++latest.current;
        try {
            const res = await call();
            if (!res.data) throw new Error(failure);
            if (request === latest.current) setData(res.data);
            if (success) toast.success(success);
        } catch {
            toast.error(failure);
        }
    }, []);

    const layout = toLayout(data?.layout) ?? (failed ? EMPTY_LAYOUT : null);

    const change = useCallback(
        (next: Layout) => {
            // Shown at once; the saved copy comes back from the API.
            setData((current) => (current ? { ...current, layout: next, source: "person" } : current));
            setFailed(false);
            void send(
                () => saveHomeLayoutApiV1DashboardLayoutPut({ body: next }),
                "Couldn't save your Home layout. Check your connection and try again.",
            );
        },
        [send],
    );

    const reset = useCallback(
        () => void send(() => resetHomeLayoutApiV1DashboardLayoutDelete(), "Couldn't reset your Home layout."),
        [send],
    );

    const saveWorkspaceDefault = useCallback(() => {
        if (!layout) return;
        void send(
            () => saveWorkspaceHomeLayoutApiV1DashboardLayoutWorkspacePut({ body: layout }),
            "Couldn't save the workspace's Home layout.",
            "Saved: members who haven't arranged their own Home now see this layout.",
        );
    }, [layout, send]);

    const clearWorkspaceDefault = useCallback(
        () =>
            void send(
                () => clearWorkspaceHomeLayoutApiV1DashboardLayoutWorkspaceDelete(),
                "Couldn't clear the workspace's Home layout.",
                "Cleared: members who haven't arranged their own Home see the standard layout.",
            ),
        [send],
    );

    return {
        layout,
        source: data?.source ?? null,
        workspaceDefault: toLayout(data?.workspace_default),
        canSetWorkspaceDefault: data?.can_set_workspace_default ?? false,
        change,
        reset,
        saveWorkspaceDefault,
        clearWorkspaceDefault,
    };
}
