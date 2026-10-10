/**
 * Remembers, across the OAuth full-page redirect, which errored connection a
 * new sign-in replaces, so the page can offer to remove it afterwards.
 * Per-tab (sessionStorage) and best-effort: storage may be unavailable.
 */

const KEY = "fallcha.integrations.reconnect";
/** Matches the OAuth flow's lifetime on the server (10 minutes). */
const MAX_AGE_MS = 10 * 60 * 1000;

export interface PendingReconnect {
    provider: string;
    oldConnectionId: string;
}

interface Stored extends PendingReconnect {
    savedAt: number;
}

export function rememberReconnect(value: PendingReconnect, now: number = Date.now()): void {
    try {
        const stored: Stored = { ...value, savedAt: now };
        window.sessionStorage.setItem(KEY, JSON.stringify(stored));
    } catch {
        // Storage blocked: the old connection simply isn't offered for removal.
    }
}

export function forgetReconnect(): void {
    try {
        window.sessionStorage.removeItem(KEY);
    } catch {
        // ignore
    }
}

/** The remembered reconnect for this provider, if recent; always clears it. */
export function takeReconnect(provider: string | null, now: number = Date.now()): PendingReconnect | null {
    let raw: string | null = null;
    try {
        raw = window.sessionStorage.getItem(KEY);
    } catch {
        return null;
    }
    forgetReconnect();
    if (!raw || !provider) return null;
    try {
        const parsed: unknown = JSON.parse(raw);
        if (typeof parsed !== "object" || parsed === null) return null;
        const { provider: p, oldConnectionId, savedAt } = parsed as Partial<Stored>;
        if (p !== provider || typeof oldConnectionId !== "string" || typeof savedAt !== "number") return null;
        if (now - savedAt > MAX_AGE_MS) return null;
        return { provider: p, oldConnectionId };
    } catch {
        return null;
    }
}
