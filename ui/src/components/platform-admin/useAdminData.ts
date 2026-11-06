import { useCallback, useEffect, useRef, useState } from "react";

import { useAuth } from "@/lib/auth";

/**
 * Load one platform admin resource once signed in. `reload` refetches (after
 * a change); `deps` refetch when they change (search, page).
 */
export function useAdminData<T>(load: () => Promise<T>, deps: unknown[] = []) {
    const { loading: authLoading, isAuthenticated } = useAuth();
    const [data, setData] = useState<T | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const loadRef = useRef(load);
    loadRef.current = load;
    const requestId = useRef(0);

    const reload = useCallback(async () => {
        const id = ++requestId.current;
        setLoading(true);
        try {
            const result = await loadRef.current();
            if (id === requestId.current) {
                setData(result);
                setError(null);
            }
        } catch (err) {
            if (id === requestId.current) {
                setError(err instanceof Error ? err.message : "Request failed");
            }
        } finally {
            if (id === requestId.current) setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (authLoading || !isAuthenticated) return;
        void reload();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [authLoading, isAuthenticated, reload, ...deps]);

    return { data, error, loading, reload, setData };
}
