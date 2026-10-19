'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import {
    integrationErrorMessage,
    isUnavailableError,
    oauthFailureMessage,
    parseIntegrationReturn,
} from '@/app/integrations/messages';
import { activateConnection, isTrustedAuthorizationUrl, startOAuth } from '@/app/integrations/oauthCalls';
import {
    clearOAuthPopupMarker,
    listenForOAuthReturn,
    markOAuthPopup,
    openOAuthPopup,
} from '@/app/integrations/oauthPopup';
import { rememberPendingOAuth, takePendingOAuth } from '@/app/integrations/pendingOAuth';
import {
    listConnectionsApiV1IntegrationsConnectionsGet,
    listProviderAppsApiV1IntegrationsProviderAppsGet,
} from '@/client/sdk.gen';
import type { IntegrationConnectionResponse } from '@/client/types.gen';
import { useOrgConfig } from '@/context/OrgConfigContext';
import { INTEGRATION_AUTH_FAMILY, usableConnection } from '@/lib/agentTemplates';

/**
 * - `ready`: can connect here, in a sign-in pop-up (the server has its own
 *   Google sign-in).
 * - `connecting`: waiting for that pop-up.
 * - `in_integrations`: can connect, but on the Integrations page (the
 *   workspace signs in with its own OAuth client); checked again on return.
 * - `needs_admin`: this user's role can't connect integrations.
 * - `unavailable`: calendar connections are switched off on this server.
 */
export type ConnectStatus =
    | 'loading'
    | 'connected'
    | 'ready'
    | 'connecting'
    | 'in_integrations'
    | 'needs_admin'
    | 'unavailable';

export interface IntegrationConnect {
    status: ConnectStatus;
    connection: IntegrationConnectionResponse | null;
    error: string | null;
    connect: () => void;
    /** Stops waiting for a sign-in the user abandoned. */
    cancel: () => void;
}

/**
 * Whether the workspace has *provider* connected, and a one-click way to
 * connect it without leaving the current screen: sign-in runs in a pop-up
 * (see app/integrations/oauthPopup.ts) and the connection is finished here,
 * with the `browser_nonce` this window keeps. Where that isn't possible it
 * says why (see ConnectStatus), so the screen never just hides the option.
 */
export function useIntegrationConnect(provider: string, enabled: boolean): IntegrationConnect {
    const { can } = useOrgConfig();
    // Connecting installs the calendar as an agent tool, so it takes both.
    const canConnect = can('integrations:write') && can('agents:write');
    const [status, setStatus] = useState<ConnectStatus>('loading');
    const [connection, setConnection] = useState<IntegrationConnectionResponse | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [appId, setAppId] = useState<string | null>(null);
    const popupRef = useRef<Window | null>(null);

    const load = useCallback(async (): Promise<ConnectStatus> => {
        const [connections, apps] = await Promise.all([
            listConnectionsApiV1IntegrationsConnectionsGet(),
            listProviderAppsApiV1IntegrationsProviderAppsGet(),
        ]);
        if (connections.error || !connections.data) {
            if (isUnavailableError(connections.error)) return 'unavailable';
            return canConnect ? 'unavailable' : 'needs_admin';
        }
        const usable = usableConnection(connections.data.connections, provider);
        setConnection(usable);
        if (usable) return 'connected';
        if (!canConnect) return 'needs_admin';
        const family = INTEGRATION_AUTH_FAMILY[provider] ?? provider;
        const managed = (apps.data?.provider_apps ?? []).find(
            (app) => app.managed && (app.provider === provider || app.provider === family),
        );
        setAppId(managed?.id ?? null);
        return managed ? 'ready' : 'in_integrations';
    }, [canConnect, provider]);

    useEffect(() => {
        if (!enabled) return;
        let cancelled = false;
        setStatus('loading');
        load()
            .then((next) => !cancelled && setStatus(next))
            .catch(() => !cancelled && setStatus('unavailable'));
        return () => {
            cancelled = true;
        };
    }, [enabled, load]);

    // Connected on the Integrations page in another tab: notice on return.
    const elsewhere = enabled && status === 'in_integrations';
    useEffect(() => {
        if (!elsewhere) return;
        const onFocus = () => {
            load()
                .then((next) => setStatus((current) => (current === 'in_integrations' ? next : current)))
                .catch(() => {});
        };
        window.addEventListener('focus', onFocus);
        return () => window.removeEventListener('focus', onFocus);
    }, [elsewhere, load]);

    // The pop-up hands the provider's return back here.
    const waiting = status === 'connecting';
    useEffect(() => {
        if (!waiting) return;
        const stop = listenForOAuthReturn(async (params) => {
            const result = parseIntegrationReturn(params);
            if (!result || result.kind === 'error') {
                setError(oauthFailureMessage(result?.reason ?? 'unknown'));
                setStatus('ready');
                return;
            }
            const pending = takePendingOAuth(result.provider ?? provider);
            if (!pending) {
                setError('We couldn’t confirm the sign-in. Please try again.');
                setStatus('ready');
                return;
            }
            const response = await activateConnection(result.connectionId, pending.nonce);
            if (response.error || !response.data || !response.data.tool_uuids?.length) {
                setError(integrationErrorMessage(response.error, 'Couldn’t finish connecting. Please try again.'));
                setStatus('ready');
                return;
            }
            setConnection(response.data);
            setStatus('connected');
        });
        return () => {
            stop();
            clearOAuthPopupMarker();
        };
    }, [waiting, provider]);

    const cancel = useCallback(() => {
        popupRef.current?.close();
        popupRef.current = null;
        setStatus((current) => (current === 'connecting' ? 'ready' : current));
    }, []);

    const connect = useCallback(() => {
        if (!appId) return;
        setError(null);
        // Open the window inside the click, or the browser blocks it.
        const popup = openOAuthPopup();
        if (!popup) {
            setError('Your browser blocked the sign-in window. Allow pop-ups for this site and try again.');
            return;
        }
        popupRef.current = popup;
        markOAuthPopup(provider);
        setStatus('connecting');
        (async () => {
            const response = await startOAuth({ provider, provider_app_id: appId, optional_scopes: [] });
            if (response.error || !response.data) {
                popup.close();
                setError(
                    isUnavailableError(response.error)
                        ? 'Signing in isn’t set up on this server yet.'
                        : integrationErrorMessage(response.error, 'Couldn’t start the sign-in. Please try again.'),
                );
                setStatus('ready');
                return;
            }
            const { authorization_url: url, browser_nonce: nonce } = response.data;
            if (!isTrustedAuthorizationUrl(url)) {
                popup.close();
                setError('The server returned an unexpected sign-in address, so it wasn’t opened.');
                setStatus('ready');
                return;
            }
            rememberPendingOAuth(provider, { nonce });
            popup.location.href = url;
        })().catch(() => {
            popup.close();
            setError('Couldn’t reach the server. Please try again.');
            setStatus('ready');
        });
    }, [appId, provider]);

    return { status, connection, error, connect, cancel };
}
