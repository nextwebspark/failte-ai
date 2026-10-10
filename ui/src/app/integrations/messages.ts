/**
 * User-facing copy for integration states, plus the query parameters the
 * OAuth callback sends the browser back with.
 *
 * The tools service redirects to /integrations with either
 *   ?integration_result=success&connection_id=<uuid>&provider=<id>
 * or
 *   ?integration_result=error&reason=<fixed code>
 * Reason codes are a fixed set (see CallbackFailure in the tools service);
 * nothing from the provider is reflected, so unknown codes get generic copy.
 */

import { detailFromError, errorCodeFromError } from "@/lib/apiError";

export const RETURN_PARAMS = ["integration_result", "connection_id", "provider", "reason"] as const;

export type IntegrationReturn =
    | { kind: "success"; connectionId: string; provider: string | null }
    | { kind: "error"; reason: string };

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PROVIDER_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;

/** Reads the OAuth return parameters, or null when the URL carries none. */
export function parseIntegrationReturn(params: URLSearchParams): IntegrationReturn | null {
    const result = params.get("integration_result");
    if (result === "success") {
        const connectionId = params.get("connection_id") ?? "";
        if (!UUID_PATTERN.test(connectionId)) {
            return { kind: "error", reason: "invalid_return" };
        }
        const provider = params.get("provider");
        return {
            kind: "success",
            connectionId,
            provider: provider && PROVIDER_PATTERN.test(provider) ? provider : null,
        };
    }
    if (result === "error") {
        return { kind: "error", reason: params.get("reason") ?? "unknown" };
    }
    return null;
}

/** The current URL without the OAuth return parameters (path + remaining query + hash). */
export function urlWithoutReturnParams(href: string): string {
    const url = new URL(href);
    for (const key of RETURN_PARAMS) url.searchParams.delete(key);
    const query = url.searchParams.toString();
    return `${url.pathname}${query ? `?${query}` : ""}${url.hash}`;
}

const OAUTH_FAILURE_MESSAGES: Record<string, string> = {
    access_denied: "You cancelled the sign-in, or Google refused access. Nothing was connected.",
    invalid_state: "That sign-in link wasn't recognised or was already used. Please start again.",
    expired_state: "The sign-in took too long and expired. Please start again.",
    authorization_failed: "Google couldn't complete the sign-in. Please try again.",
    client_missing: "The OAuth client used for this sign-in was removed. Add it again, then reconnect.",
    token_exchange_failed:
        "Google rejected the OAuth client. Check the client ID and secret, and that the redirect URI is registered exactly as shown.",
    no_refresh_token:
        "Google didn't grant offline access. Remove this app's access in your Google account settings, then connect again.",
    scopes_missing: "Some required permissions weren't granted. Connect again and allow every requested permission.",
    internal_error: "Something went wrong on our side while connecting. Please try again.",
    invalid_return: "The sign-in returned an unexpected response. Please try again.",
};

/** Friendly copy for an OAuth callback failure code. */
export function oauthFailureMessage(reason: string): string {
    return OAUTH_FAILURE_MESSAGES[reason] ?? "The connection couldn't be completed. Please try again.";
}

export type ConnectionState = "active" | "pending" | "error" | "revoked" | "not_installed";

/** The state a connection row shows, folding in whether its tool exists. */
export function connectionState(connection: {
    status: string;
    credential_uuid?: string | null;
}): ConnectionState {
    if (connection.status === "error") return "error";
    if (connection.status === "revoked") return "revoked";
    if (connection.status === "pending") return "pending";
    if (!connection.credential_uuid) return "not_installed";
    return "active";
}

const CONNECTION_ERROR_MESSAGES: Record<string, string> = {
    grant_revoked: "Access was revoked or expired in the Google account. Reconnect to restore it.",
    client_rejected: "Google no longer accepts this OAuth client. Check it in Google Cloud, then reconnect.",
    client_missing: "The OAuth client for this connection was removed. Add it again and reconnect.",
};

/** Friendly copy for a connection in the error state. */
export function connectionErrorMessage(connection: {
    error_code?: string | null;
    last_error?: string | null;
}): string {
    if (connection.error_code && CONNECTION_ERROR_MESSAGES[connection.error_code]) {
        return CONNECTION_ERROR_MESSAGES[connection.error_code];
    }
    return connection.last_error?.trim() || "The last check failed. Test the connection or reconnect.";
}

/** True when only reconnecting can fix the connection. */
export function needsReconnect(connection: { status: string; error_code?: string | null }): boolean {
    return connection.status === "error" && Boolean(connection.error_code);
}

const UNAVAILABLE_CODES = new Set(["integration_unavailable", "tools_service_not_configured"]);

/** True when the server has no integrations backend (or this feature) configured. */
export function isUnavailableError(error: unknown): boolean {
    const code = errorCodeFromError(error);
    return code !== undefined && UNAVAILABLE_CODES.has(code);
}

/** A display message for an integrations API error, without internal detail. */
export function integrationErrorMessage(error: unknown, fallback: string): string {
    switch (errorCodeFromError(error)) {
        case "integration_unavailable":
        case "tools_service_not_configured":
            return "Integrations aren't configured on this server.";
        case "tools_service_unavailable":
            return "The integrations service isn't responding. Please try again shortly.";
        default:
            return detailFromError(error, fallback);
    }
}

const SCOPE_LABELS: Record<string, string> = {
    "https://www.googleapis.com/auth/calendar.events": "Create and change calendar events",
    "https://www.googleapis.com/auth/calendar.readonly": "See calendars and free/busy times",
    "https://www.googleapis.com/auth/calendar": "Full access to Google Calendar",
    "https://www.googleapis.com/auth/spreadsheets.readonly": "Read Google Sheets",
    "https://www.googleapis.com/auth/spreadsheets": "Read and edit Google Sheets",
    "https://www.googleapis.com/auth/gmail.send": "Send email as you",
};

/** A readable name for an OAuth scope URL. */
export function scopeLabel(scope: string): string {
    if (SCOPE_LABELS[scope]) return SCOPE_LABELS[scope];
    const tail = scope.split("/").pop() ?? scope;
    return tail.replace(/[._]/g, " ");
}

const AUTH_MODE_LABELS: Record<string, string> = {
    oauth2: "Sign in with your account",
    service_account: "Service account key",
    api_key: "API key",
    none: "No sign-in",
};

export function authModeLabel(mode: string): string {
    return AUTH_MODE_LABELS[mode] ?? mode;
}

/** The key OAuth clients and reusable keys are shared under: the family, else the id. */
export function credentialFamily(provider: { id: string; auth_family?: string | null }): string {
    return provider.auth_family || provider.id;
}

export interface SyncInfo {
    status: string;
    started_at: string;
    finished_at?: string | null;
    last_synced_at?: string | null;
    item_count: number;
    last_error?: string | null;
    note?: string | null;
}

export function isSyncing(sync: SyncInfo | null | undefined): boolean {
    return sync?.status === "running";
}

function shortDate(value: string): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/**
 * One line describing a connection's sync, e.g.
 * "42 products · last synced 10 Oct 2026, 11:00 · stopped at 2000 pages".
 */
export function syncSummary(sync: SyncInfo | null | undefined, itemLabel = "items"): string {
    if (!sync) return `Not synced yet. Sync to import ${itemLabel}.`;
    if (sync.status === "running") return `Syncing ${itemLabel}…`;
    const synced = sync.last_synced_at ? shortDate(sync.last_synced_at) : null;
    if (sync.status === "failed") {
        const kept = synced ? ` · ${sync.item_count} ${itemLabel} from ${synced}` : "";
        return `Last sync failed: ${sync.last_error || "unknown error"}${kept}`;
    }
    const parts = [`${sync.item_count} ${itemLabel}`];
    if (synced) parts.push(`last synced ${synced}`);
    if (sync.note) parts.push(sync.note);
    return parts.join(" · ");
}

/** The sync button's label: "Sync products". */
export function syncButtonLabel(itemLabel: string | null | undefined): string {
    return itemLabel ? `Sync ${itemLabel}` : "Sync now";
}

const EMAIL = /^[^\s@]+@[^\s@]+$/;

/** True for an email address (only those can be a sign-in hint). */
export function isEmail(value: string | null | undefined): value is string {
    return Boolean(value && EMAIL.test(value));
}

/** A function's short human label: its summary, else its name in words. */
export function humanToolName(tool: { name: string; summary?: string | null }): string {
    const summary = tool.summary?.trim();
    if (summary) return summary;
    const words = tool.name.replace(/[_-]+/g, " ").trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
}
