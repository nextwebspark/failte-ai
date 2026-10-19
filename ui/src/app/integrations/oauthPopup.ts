import { parseIntegrationReturn } from "./messages";
import { PENDING_OAUTH_TTL_MS } from "./pendingOAuth";

/**
 * Sign-in from inside another screen (e.g. the Create agent dialog) runs in a
 * pop-up so that screen keeps its state. The provider still returns to
 * /integrations; there, a fresh pop-up marker says the sign-in belongs to
 * another window, so the page hands the return over on a same-origin
 * BroadcastChannel and closes, and the waiting screen finishes the
 * connection with the `browser_nonce` it holds.
 *
 * A BroadcastChannel and a localStorage marker, not `window.opener` and
 * `window.name`: the provider's sign-in page may sever the opener and clear
 * the window name on its way back.
 */

const MARKER_KEY = "lightmove.oauth.popup";
const CHANNEL = "lightmove-oauth";
export const OAUTH_RETURN_MESSAGE = "lightmove:oauth-return";

interface Marker {
    provider: string;
    at: number;
}

export interface OAuthReturnMessage {
    type: typeof OAUTH_RETURN_MESSAGE;
    search: string;
}

/** Notes that *provider*'s next sign-in return belongs to a waiting screen. */
export function markOAuthPopup(provider: string, now: number = Date.now()): void {
    try {
        window.localStorage.setItem(MARKER_KEY, JSON.stringify({ provider, at: now } satisfies Marker));
    } catch {
        // Storage blocked: the return lands on /integrations, which finishes it there.
    }
}

export function clearOAuthPopupMarker(): void {
    try {
        window.localStorage.removeItem(MARKER_KEY);
    } catch {
        // ignore
    }
}

function freshMarker(now: number): Marker | null {
    try {
        const parsed: unknown = JSON.parse(window.localStorage.getItem(MARKER_KEY) ?? "null");
        if (typeof parsed !== "object" || parsed === null) return null;
        const { provider, at } = parsed as Partial<Marker>;
        if (typeof provider !== "string" || typeof at !== "number") return null;
        return now - at <= PENDING_OAUTH_TTL_MS && now >= at ? { provider, at } : null;
    } catch {
        return null;
    }
}

/** Opens the (blank) sign-in pop-up. Call it straight from the click, or it is blocked. */
export function openOAuthPopup(): Window | null {
    const width = 520;
    const height = 700;
    const left = Math.max(0, window.screenX + (window.outerWidth - width) / 2);
    const top = Math.max(0, window.screenY + (window.outerHeight - height) / 2);
    return window.open("about:blank", "lightmove-oauth", `popup,width=${width},height=${height},left=${left},top=${top}`);
}

/**
 * On /integrations: when the URL carries an OAuth return that a waiting
 * screen asked for, broadcast it, clear the marker and try to close this
 * window. Returns whether it did; the caller then only says it can be closed.
 */
export function handOffOAuthReturn(now: number = Date.now()): boolean {
    const search = window.location.search;
    const result = parseIntegrationReturn(new URLSearchParams(search));
    if (!result) return false;
    const marker = freshMarker(now);
    if (!marker) return false;
    if (result.kind === "success" && result.provider && result.provider !== marker.provider) return false;
    if (typeof BroadcastChannel === "undefined") return false;
    clearOAuthPopupMarker();
    const channel = new BroadcastChannel(CHANNEL);
    channel.postMessage({ type: OAUTH_RETURN_MESSAGE, search } satisfies OAuthReturnMessage);
    channel.close();
    window.close();
    return true;
}

/** Calls *onReturn* with each sign-in return a pop-up hands over. Returns the unsubscribe. */
export function listenForOAuthReturn(onReturn: (params: URLSearchParams) => void): () => void {
    if (typeof BroadcastChannel === "undefined") return () => {};
    const channel = new BroadcastChannel(CHANNEL);
    channel.onmessage = (event: MessageEvent) => {
        const data = event.data as Partial<OAuthReturnMessage> | null;
        if (!data || data.type !== OAUTH_RETURN_MESSAGE || typeof data.search !== "string") return;
        onReturn(new URLSearchParams(data.search));
    };
    return () => channel.close();
}
