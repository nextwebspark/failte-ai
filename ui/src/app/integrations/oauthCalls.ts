import {
    activateConnectionApiV1IntegrationsConnectionsConnectionIdActivatePost,
    startOauthApiV1IntegrationsOauthStartPost,
} from "@/client/sdk.gen";
import type { StartOAuthRequest } from "@/client/types.gen";

/**
 * `oauth/start` sets an HttpOnly cookie that binds the flow to this browser,
 * and `activate` must send it back to confirm the new connection. Both calls
 * therefore include credentials, also when the API is on another origin.
 */
export const OAUTH_FETCH_OPTIONS = { credentials: "include" } as const satisfies RequestInit;

export function startOAuth(body: StartOAuthRequest) {
    return startOauthApiV1IntegrationsOauthStartPost({ body, ...OAUTH_FETCH_OPTIONS });
}

export function activateConnection(connectionId: string) {
    return activateConnectionApiV1IntegrationsConnectionsConnectionIdActivatePost({
        path: { connection_id: connectionId },
        ...OAUTH_FETCH_OPTIONS,
    });
}
