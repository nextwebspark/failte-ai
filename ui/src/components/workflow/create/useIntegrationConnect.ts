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
import { INTEGRATION_AUTH_FAMILY, usableConnection } from '@/lib/agentTemplates';

export type ConnectStatus = 'loading' | 'connected' | 'disconnected' | 'connecting' | 'unavailable';

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
 * with the `browser_nonce` this window keeps.
 * `unavailable` means this workspace can't connect it from here (no
 * permission, integrations off, or no ready-made Google sign-in).
 */
export function useIntegrationConnect(provider: string, enabled: boolean): IntegrationConnect {
    const [status, setStatus] = useState<ConnectStatus>('loading');
    const [connection, setConnection] = useState<IntegrationConnectionResponse | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [appId, setAppId] = useState<string | null>(null);
    const popupRef = useRef<Window | null>(null);

    useEffect(() => {
        if (!enabled) return;
        let cancelled = false;
        setStatus('loading');
        (async () => {
            const [connections, apps] = await Promise.all([
                listConnectionsApiV1IntegrationsConnectionsGet(),
                listProviderAppsApiV1IntegrationsProviderAppsGet(),
            ]);
            if (cancelled) return;
            if (connections.error || !connections.data) {
                setStatus('unavailable');
                return;
            }
            const usable = usableConnection(connections.data.connections, provider);
            const family = INTEGRATION_AUTH_FAMILY[provider] ?? provider;
            const managed = (apps.data?.provider_apps ?? []).find(
                (app) => app.managed && (app.provider === provider || app.provider === family),
            );
            setAppId(managed?.id ?? null);
            setConnection(usable);
            setStatus(usable ? 'connected' : managed ? 'disconnected' : 'unavailable');
        })().catch(() => {
            if (!cancelled) setStatus('unavailable');
        });
        return () => {
            cancelled = true;
        };
    }, [enabled, provider]);

    // The pop-up hands the provider's return back here.
    const waiting = status === 'connecting';
    useEffect(() => {
        if (!waiting) return;
        const stop = listenForOAuthReturn(async (params) => {
            const result = parseIntegrationReturn(params);
            if (!result || result.kind === 'error') {
                setError(oauthFailureMessage(result?.reason ?? 'unknown'));
                setStatus('disconnected');
                return;
            }
            const pending = takePendingOAuth(result.provider ?? provider);
            if (!pending) {
                setError('We couldn’t confirm the sign-in. Please try again.');
                setStatus('disconnected');
                return;
            }
            const response = await activateConnection(result.connectionId, pending.nonce);
            if (response.error || !response.data || !response.data.tool_uuids?.length) {
                setError(integrationErrorMessage(response.error, 'Couldn’t finish connecting. Please try again.'));
                setStatus('disconnected');
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
        setStatus((current) => (current === 'connecting' ? 'disconnected' : current));
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
                setStatus('disconnected');
                return;
            }
            const { authorization_url: url, browser_nonce: nonce } = response.data;
            if (!isTrustedAuthorizationUrl(url)) {
                popup.close();
                setError('The server returned an unexpected sign-in address, so it wasn’t opened.');
                setStatus('disconnected');
                return;
            }
            rememberPendingOAuth(provider, { nonce });
            popup.location.href = url;
        })().catch(() => {
            popup.close();
            setError('Couldn’t reach the server. Please try again.');
            setStatus('disconnected');
        });
    }, [appId, provider]);

    return { status, connection, error, connect, cancel };
}
