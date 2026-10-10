import {
    activateConnectionApiV1IntegrationsConnectionsConnectionIdActivatePost,
    startOauthApiV1IntegrationsOauthStartPost,
} from "@/client/sdk.gen";
import type { StartOAuthRequest } from "@/client/types.gen";

export function startOAuth(body: StartOAuthRequest) {
    return startOauthApiV1IntegrationsOauthStartPost({ body });
}

/**
 * Installs a connection as an agent tool. A just-authorized OAuth connection
 * also needs the `browser_nonce` its `oauth/start` returned.
 */
export function activateConnection(connectionId: string, browserNonce?: string) {
    return activateConnectionApiV1IntegrationsConnectionsConnectionIdActivatePost({
        path: { connection_id: connectionId },
        ...(browserNonce ? { body: { browser_nonce: browserNonce } } : {}),
    });
}

/** Hosts the browser may be sent to for sign-in. */
export const TRUSTED_AUTHORIZE_HOSTS: readonly string[] = ["accounts.google.com"];

/** True for an https URL on a trusted sign-in host. */
export function isTrustedAuthorizationUrl(
    value: string,
    hosts: readonly string[] = TRUSTED_AUTHORIZE_HOSTS,
): boolean {
    let url: URL;
    try {
        url = new URL(value);
    } catch {
        return false;
    }
    return url.protocol === "https:" && !url.username && !url.password && hosts.includes(url.host);
}
