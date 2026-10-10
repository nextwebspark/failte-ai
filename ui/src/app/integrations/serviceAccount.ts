/**
 * Client-side checks for a pasted or uploaded Google service-account JSON
 * key. The key is a secret: callers must never log it, and error messages
 * here never include any of its content.
 */

export type ServiceAccountKey = Record<string, unknown> & {
    type: "service_account";
    client_email: string;
    private_key: string;
};

export type ParsedServiceAccount =
    | { ok: true; key: ServiceAccountKey; clientEmail: string }
    | { ok: false; error: string };

/** Largest key file accepted; real keys are ~2.3 KB. */
export const MAX_KEY_BYTES = 64 * 1024;

export function parseServiceAccountKey(text: string): ParsedServiceAccount {
    const trimmed = text.trim();
    if (!trimmed) return { ok: false, error: "Paste or upload the JSON key." };
    if (trimmed.length > MAX_KEY_BYTES) return { ok: false, error: "That file is too large to be a key." };

    let parsed: unknown;
    try {
        parsed = JSON.parse(trimmed);
    } catch {
        return { ok: false, error: "That isn't valid JSON. Use the key file exactly as Google downloaded it." };
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        return { ok: false, error: "The key must be a JSON object." };
    }
    const key = parsed as Record<string, unknown>;
    if (key.type !== "service_account") {
        return { ok: false, error: "This isn't a service-account key (\"type\" must be \"service_account\")." };
    }
    const email = key.client_email;
    if (typeof email !== "string" || !/^[^@\s]+@[^@\s]+$/.test(email)) {
        return { ok: false, error: "The key has no valid \"client_email\"." };
    }
    const privateKey = key.private_key;
    if (typeof privateKey !== "string" || !privateKey.includes("PRIVATE KEY")) {
        return { ok: false, error: "The key has no \"private_key\"." };
    }
    return {
        ok: true,
        key: { ...key, type: "service_account", client_email: email, private_key: privateKey },
        clientEmail: email,
    };
}
