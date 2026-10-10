// @vitest-environment node

import { describe, expect, it } from "vitest";

import { parseServiceAccountKey } from "./serviceAccount";

const PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg-not-a-real-key\n-----END PRIVATE KEY-----\n";
const KEY = {
    type: "service_account",
    project_id: "acme",
    private_key_id: "abc123",
    private_key: PRIVATE_KEY,
    client_email: "booking@acme.iam.gserviceaccount.com",
};

describe("parseServiceAccountKey", () => {
    it("accepts a Google key and keeps every field", () => {
        const result = parseServiceAccountKey(`  ${JSON.stringify(KEY)}\n`);
        expect(result).toEqual({ ok: true, key: KEY, clientEmail: KEY.client_email });
    });

    it.each([
        ["", /Paste or upload/],
        ["{not json", /isn't valid JSON/],
        ["[1, 2]", /JSON object/],
        [JSON.stringify({ ...KEY, type: "authorized_user" }), /service-account key/],
        [JSON.stringify({ ...KEY, client_email: "nope" }), /client_email/],
        [JSON.stringify({ ...KEY, private_key: undefined }), /private_key/],
        [JSON.stringify({ ...KEY, private_key: "hunter2" }), /private_key/],
    ])("rejects %#", (text, message) => {
        const result = parseServiceAccountKey(text);
        expect(result.ok).toBe(false);
        if (!result.ok) expect(result.error).toMatch(message);
    });

    it("never echoes key material in errors", () => {
        const result = parseServiceAccountKey(JSON.stringify({ ...KEY, client_email: "secret-value" }));
        expect(result.ok).toBe(false);
        if (!result.ok) {
            expect(result.error).not.toContain("secret-value");
            expect(result.error).not.toContain("BEGIN PRIVATE KEY");
        }
    });

    it("rejects oversized input", () => {
        const result = parseServiceAccountKey(" ".repeat(10) + "x".repeat(70 * 1024));
        expect(result).toEqual({ ok: false, error: "That file is too large to be a key." });
    });
});
