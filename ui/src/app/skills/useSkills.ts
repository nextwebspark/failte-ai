"use client";

import { type Dispatch, type SetStateAction, useCallback, useEffect, useRef, useState } from "react";

import {
    getAuthUserApiV1UserAuthUserGet,
    listLibrarySkillsApiV1SkillLibraryGet,
    listSkillsApiV1SkillsGet,
} from "@/client/sdk.gen";
import type { LibrarySkillSummaryResponse, SkillSummaryResponse } from "@/client/types.gen";
import { detailFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

import { NETWORK_ERROR } from "./errors";

interface ListState<T> {
    items: T[];
    loading: boolean;
    error: string | null;
    refresh: () => Promise<void>;
    setItems: Dispatch<SetStateAction<T[]>>;
}

function useAuthedList<T>(
    enabled: boolean,
    load: () => Promise<{ items: T[] } | { error: string }>,
): ListState<T> {
    const { user, loading: authLoading } = useAuth();
    const [items, setItems] = useState<T[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const hasFetched = useRef(false);

    const refresh = useCallback(async () => {
        try {
            const result = await load();
            if ("error" in result) {
                setError(result.error);
                return;
            }
            setItems(result.items);
            setError(null);
        } catch {
            setError(NETWORK_ERROR);
        } finally {
            setLoading(false);
        }
    }, [load]);

    useEffect(() => {
        if (!enabled || authLoading || !user || hasFetched.current) return;
        hasFetched.current = true;
        void refresh();
    }, [enabled, authLoading, user, refresh]);

    return { items, loading, error, refresh, setItems };
}

const loadWorkspaceSkills = async (): Promise<{ items: SkillSummaryResponse[] } | { error: string }> => {
    const response = await listSkillsApiV1SkillsGet();
    if (response.error || !response.data) return { error: detailFromError(response.error, "Couldn't load your skills") };
    return { items: response.data.skills };
};

const loadLibrarySkills = async (): Promise<{ items: LibrarySkillSummaryResponse[] } | { error: string }> => {
    const response = await listLibrarySkillsApiV1SkillLibraryGet();
    if (response.error || !response.data) {
        return { error: detailFromError(response.error, "Couldn't load the skill library") };
    }
    return { items: response.data.skills };
};

/** This workspace's active skills, loaded once auth is ready. */
export function useWorkspaceSkills(enabled: boolean): ListState<SkillSummaryResponse> {
    return useAuthedList(enabled, loadWorkspaceSkills);
}

/** Library skills (platform admins also get drafts and deprecated ones). */
export function useLibrarySkills(enabled: boolean): ListState<LibrarySkillSummaryResponse> {
    return useAuthedList(enabled, loadLibrarySkills);
}

/**
 * Whether the signed-in user is a platform admin (`is_superuser`), who can
 * manage the skill library: null until known, false on any failure. The API
 * enforces it regardless.
 */
export function usePlatformAdmin(): boolean | null {
    const { user, loading: authLoading } = useAuth();
    const [isAdmin, setIsAdmin] = useState<boolean | null>(null);
    const hasFetched = useRef(false);

    useEffect(() => {
        if (authLoading || !user || hasFetched.current) return;
        hasFetched.current = true;
        void (async () => {
            try {
                const response = await getAuthUserApiV1UserAuthUserGet();
                setIsAdmin(Boolean(response.data?.is_superuser));
            } catch {
                setIsAdmin(false);
            }
        })();
    }, [authLoading, user]);

    return isAdmin;
}
