"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
    getCatalogApiV1IntegrationsCatalogGet,
    listConnectionsApiV1IntegrationsConnectionsGet,
    listProviderAppsApiV1IntegrationsProviderAppsGet,
} from "@/client/sdk.gen";
import type {
    IntegrationConnectionResponse,
    IntegrationProvider,
    ProviderAppResponse,
} from "@/client/types.gen";
import { useAuth } from "@/lib/auth";

import { integrationErrorMessage, isUnavailableError } from "./messages";

const NETWORK_ERROR = "Couldn't reach the server. Check your connection and try again.";

export interface IntegrationsState {
    providers: IntegrationProvider[];
    connections: IntegrationConnectionResponse[];
    providerApps: ProviderAppResponse[];
    /** True until the first load finishes (and during a full reload). */
    loading: boolean;
    /** The server has no integrations backend configured. */
    unavailable: boolean;
    /** A failure of the initial load; later refresh failures are toasts. */
    error: string | null;
    refresh: () => Promise<void>;
    /** Reloads the connections; resolves false (after a toast) on failure. */
    refreshConnections: () => Promise<boolean>;
    /** Reloads the connections without a toast (for polling). */
    reloadConnectionsQuietly: () => Promise<boolean>;
    upsertConnection: (connection: IntegrationConnectionResponse) => void;
    addProviderApp: (app: ProviderAppResponse) => void;
}

/**
 * Loads the catalog, connections and OAuth clients once auth is ready and
 * `enabled` (the caller may read integrations) is true.
 */
export function useIntegrations(enabled: boolean): IntegrationsState {
    const { user, loading: authLoading } = useAuth();
    const [providers, setProviders] = useState<IntegrationProvider[]>([]);
    const [connections, setConnections] = useState<IntegrationConnectionResponse[]>([]);
    const [providerApps, setProviderApps] = useState<ProviderAppResponse[]>([]);
    const [loading, setLoading] = useState(true);
    const [unavailable, setUnavailable] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const hasFetched = useRef(false);
    // Bumped by every load and every local update: a response is applied only
    // if nothing newer happened meanwhile, so a slow (e.g. polling) request
    // can never revert fresher state.
    const connectionsVersion = useRef(0);

    const loadConnections = useCallback(async (): Promise<string | null> => {
        const version = ++connectionsVersion.current;
        try {
            const response = await listConnectionsApiV1IntegrationsConnectionsGet();
            if (response.error) return integrationErrorMessage(response.error, "Couldn't load your connections");
            if (version === connectionsVersion.current) setConnections(response.data?.connections ?? []);
            return null;
        } catch {
            return NETWORK_ERROR;
        }
    }, []);

    const loadProviderApps = useCallback(async () => {
        try {
            const response = await listProviderAppsApiV1IntegrationsProviderAppsGet();
            // OAuth clients are optional extras: a failure here only hides them.
            if (!response.error) setProviderApps(response.data?.provider_apps ?? []);
        } catch {
            // ignore
        }
    }, []);

    const refreshConnections = useCallback(async () => {
        const failure = await loadConnections();
        if (failure) toast.error(failure);
        return failure === null;
    }, [loadConnections]);

    const reloadConnectionsQuietly = useCallback(
        async () => (await loadConnections()) === null,
        [loadConnections],
    );

    const refresh = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const catalog = await getCatalogApiV1IntegrationsCatalogGet();
            if (catalog.error) {
                if (isUnavailableError(catalog.error)) setUnavailable(true);
                else setError(integrationErrorMessage(catalog.error, "Couldn't load integrations"));
                return;
            }
            setUnavailable(false);
            setProviders(catalog.data?.providers ?? []);
            const [failure] = await Promise.all([loadConnections(), loadProviderApps()]);
            if (failure) setError(failure);
        } catch {
            setError(NETWORK_ERROR);
        } finally {
            setLoading(false);
        }
    }, [loadConnections, loadProviderApps]);

    useEffect(() => {
        if (!enabled || authLoading || !user || hasFetched.current) return;
        hasFetched.current = true;
        void refresh();
    }, [enabled, authLoading, user, refresh]);

    const upsertConnection = useCallback((connection: IntegrationConnectionResponse) => {
        connectionsVersion.current += 1;
        setConnections((current) => {
            const index = current.findIndex((c) => c.id === connection.id);
            if (index === -1) return [connection, ...current];
            const next = [...current];
            next[index] = connection;
            return next;
        });
    }, []);

    const addProviderApp = useCallback((app: ProviderAppResponse) => {
        setProviderApps((current) => [app, ...current.filter((a) => a.id !== app.id)]);
    }, []);

    return {
        providers,
        connections,
        providerApps,
        loading,
        unavailable,
        error,
        refresh,
        refreshConnections,
        reloadConnectionsQuietly,
        upsertConnection,
        addProviderApp,
    };
}
