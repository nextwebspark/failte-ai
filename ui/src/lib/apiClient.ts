import type { Client } from '@/client/client';
import type { CreateClientConfig } from '@/client/client.gen';

export function getServerBackendUrl() {
    return process.env.BACKEND_URL || 'http://api:8000';
}

/**
 * Resolve the base URL the browser should use to reach the backend API.
 *
 * Precedence:
 *   1. NEXT_PUBLIC_BACKEND_URL — explicit build-time operator config, always wins.
 *   2. backendApiEndpoint — the URL the backend reports it is running on via /health
 *      (surfaced through AppConfigContext). This is the address the browser actually
 *      reaches the backend at; for a backend on a private IP it is that private IP.
 *      Unknown at module init, so createClientConfig seeds without it and
 *      AppConfigProvider upgrades the client once /health resolves.
 *   3. window.location.origin — same-origin public deployment.
 *
 * This is the browser→API order. It is intentionally NOT tunnel-aware: the
 * Cloudflare tunnel URL is only for externally-hosted consumers (telephony
 * webhooks, MCP, external API triggers) that cannot reach a private IP — see
 * resolveWebhookBaseUrl.
 */
export function resolveBrowserBackendUrl(backendApiEndpoint?: string | null): string {
    return (
        process.env.NEXT_PUBLIC_BACKEND_URL ||
        backendApiEndpoint ||
        (typeof window !== 'undefined' ? window.location.origin : '')
    );
}

export const createClientConfig: CreateClientConfig = (config) => {
    // Use different URLs for server-side vs client-side
    const isServer = typeof window === 'undefined';
    let baseUrl: string;

    if (isServer) {
        baseUrl = getServerBackendUrl();
    } else {
        // The backend-reported endpoint is not known yet at module init;
        // AppConfigProvider upgrades the client base URL once /health reports it
        // (when no explicit NEXT_PUBLIC_BACKEND_URL is configured).
        baseUrl = resolveBrowserBackendUrl();
    }

    return {
        ...config,
        baseUrl,
    };
};

let interceptorRegistered = false;

/**
 * Register a request interceptor that attaches a fresh access token
 * to every outgoing SDK request. Idempotent — safe for React strict mode.
 */
export function setupAuthInterceptor(
    apiClient: Client,
    getAccessToken: () => Promise<string>,
    onSessionEnded?: () => void,
) {
    if (interceptorRegistered) return;
    interceptorRegistered = true;

    // A 401 on a signed-in page usually means the session is no longer valid
    // (expired, signed out elsewhere, or a token from another environment).
    // Confirm once with /auth/me, then end the session cleanly instead of
    // leaving a half-working page. Concurrent 401s share one check.
    let sessionCheck: Promise<void> | null = null;
    apiClient.interceptors.response.use(async (response, request) => {
        if (
            response.status !== 401 ||
            !onSessionEnded ||
            typeof window === 'undefined' ||
            new URL(request.url).pathname.includes('/auth/')
        ) {
            return response;
        }
        sessionCheck ??= (async () => {
            try {
                const token = await getAccessToken();
                const me = await fetch(new URL('/api/v1/auth/me', request.url), {
                    headers: token ? { Authorization: `Bearer ${token}` } : {},
                });
                if (me.status === 401) onSessionEnded();
            } catch {
                // Network trouble is not a session problem: leave the page as it is.
            }
        })().finally(() => {
            sessionCheck = null;
        });
        await sessionCheck;
        return response;
    });

    apiClient.interceptors.request.use(async (request) => {
        if (request.headers.get('Authorization')) {
            return request;
        }
        try {
            const token = await getAccessToken();
            request.headers.set('Authorization', `Bearer ${token}`);
        } catch {
            // If token retrieval fails, let the request proceed without auth
        }
        return request;
    });
}
