"use client";

import { useCallback, useEffect, useRef, useState } from "react";

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

export interface IntegrationsState {
    providers: IntegrationProvider[];
    connections: IntegrationConnectionResponse[];
    providerApps: ProviderAppResponse[];
    loading: boolean;
    /** The server has no integrations backend configured. */
    unavailable: boolean;
    error: string | null;
    /** Auth is ready and the first load can run. */
    ready: boolean;
    refresh: () => Promise<void>;
    refreshConnections: () => Promise<void>;
    refreshProviderApps: () => Promise<void>;
    upsertConnection: (connection: IntegrationConnectionResponse) => void;
}

export function useIntegrations(): IntegrationsState {
    const { user, loading: authLoading } = useAuth();
    const [providers, setProviders] = useState<IntegrationProvider[]>([]);
    const [connections, setConnections] = useState<IntegrationConnectionResponse[]>([]);
    const [providerApps, setProviderApps] = useState<ProviderAppResponse[]>([]);
    const [loading, setLoading] = useState(true);
    const [unavailable, setUnavailable] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const hasFetched = useRef(false);

    const refreshConnections = useCallback(async () => {
        const response = await listConnectionsApiV1IntegrationsConnectionsGet();
        if (response.error) {
            setError(integrationErrorMessage(response.error, "Couldn't load your connections"));
            return;
        }
        setConnections(response.data?.connections ?? []);
    }, []);

    const refreshProviderApps = useCallback(async () => {
        const response = await listProviderAppsApiV1IntegrationsProviderAppsGet();
        // OAuth clients are optional extras: a failure here only hides them.
        if (!response.error) setProviderApps(response.data?.provider_apps ?? []);
    }, []);

    const refresh = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const catalog = await getCatalogApiV1IntegrationsCatalogGet();
            if (catalog.error) {
                if (isUnavailableError(catalog.error)) {
                    setUnavailable(true);
                } else {
                    setError(integrationErrorMessage(catalog.error, "Couldn't load integrations"));
                }
                return;
            }
            setUnavailable(false);
            setProviders(catalog.data?.providers ?? []);
            await Promise.all([refreshConnections(), refreshProviderApps()]);
        } catch {
            setError("Couldn't reach the server. Check your connection and try again.");
        } finally {
            setLoading(false);
        }
    }, [refreshConnections, refreshProviderApps]);

    useEffect(() => {
        if (authLoading || !user || hasFetched.current) return;
        hasFetched.current = true;
        void refresh();
    }, [authLoading, user, refresh]);

    const upsertConnection = useCallback((connection: IntegrationConnectionResponse) => {
        setConnections((current) => {
            const index = current.findIndex((c) => c.id === connection.id);
            if (index === -1) return [connection, ...current];
            const next = [...current];
            next[index] = connection;
            return next;
        });
    }, []);

    return {
        providers,
        connections,
        providerApps,
        loading,
        unavailable,
        error,
        ready: !authLoading && Boolean(user),
        refresh,
        refreshConnections,
        refreshProviderApps,
        upsertConnection,
    };
}
