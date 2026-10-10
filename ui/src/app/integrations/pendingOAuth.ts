/**
 * Per-tab memory of an OAuth sign-in in flight, kept across the full-page
 * redirect to the provider and back:
 * - `nonce`: the `browser_nonce` from `oauth/start`. `activate` must send it
 *   to confirm the new connection, which binds the connection to the user and
 *   browser that started the flow. It is a secret: never log it.
 * - `replacesConnectionId`: the errored connection a reconnect replaces, so
 *   the page can offer to remove it afterwards.
 *
 * sessionStorage, keyed by provider, with the server's 10-minute flow
 * lifetime; entries are cleared when used or when the flow fails. Storage may
 * be unavailable, in which case confirming fails with a clear message.
 */

const PREFIX = "fallcha.integrations.oauth.";
export const PENDING_OAUTH_TTL_MS = 10 * 60 * 1000;

export interface PendingOAuth {
    nonce: string;
    replacesConnectionId?: string;
}

interface Stored extends PendingOAuth {
    savedAt: number;
}

export function rememberPendingOAuth(provider: string, value: PendingOAuth, now: number = Date.now()): void {
    try {
        const stored: Stored = { ...value, savedAt: now };
        window.sessionStorage.setItem(PREFIX + provider, JSON.stringify(stored));
    } catch {
        // Storage blocked: activation will report that the sign-in can't be confirmed.
    }
}

/** The pending sign-in for this provider if still fresh; always removes it. */
export function takePendingOAuth(provider: string, now: number = Date.now()): PendingOAuth | null {
    let raw: string | null = null;
    try {
        raw = window.sessionStorage.getItem(PREFIX + provider);
        window.sessionStorage.removeItem(PREFIX + provider);
    } catch {
        return null;
    }
    if (!raw) return null;
    try {
        const parsed: unknown = JSON.parse(raw);
        if (typeof parsed !== "object" || parsed === null) return null;
        const { nonce, replacesConnectionId, savedAt } = parsed as Partial<Stored>;
        if (typeof nonce !== "string" || !nonce || typeof savedAt !== "number") return null;
        if (now - savedAt > PENDING_OAUTH_TTL_MS || now < savedAt) return null;
        return typeof replacesConnectionId === "string" ? { nonce, replacesConnectionId } : { nonce };
    } catch {
        return null;
    }
}

/** Forgets every pending sign-in (e.g. after a failed callback, which names no provider). */
export function clearPendingOAuth(provider?: string): void {
    try {
        const storage = window.sessionStorage;
        if (provider) {
            storage.removeItem(PREFIX + provider);
            return;
        }
        const keys: string[] = [];
        for (let i = 0; i < storage.length; i++) {
            const key = storage.key(i);
            if (key?.startsWith(PREFIX)) keys.push(key);
        }
        for (const key of keys) storage.removeItem(key);
    } catch {
        // ignore
    }
}
