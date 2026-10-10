// @vitest-environment node

import { describe, expect, it } from "vitest";

import {
    connectionErrorMessage,
    connectionState,
    integrationErrorMessage,
    isUnavailableError,
    needsReconnect,
    oauthFailureMessage,
    parseIntegrationReturn,
    scopeLabel,
    urlWithoutReturnParams,
} from "./messages";

const CONNECTION_ID = "4f1c2d3e-5a6b-4c7d-8e9f-0a1b2c3d4e5f";

/** The fixed reason codes the tools service's OAuth callback can send (CallbackFailure). */
const CALLBACK_REASONS = [
    "invalid_state",
    "expired_state",
    "access_denied",
    "authorization_failed",
    "client_missing",
    "token_exchange_failed",
    "no_refresh_token",
    "scopes_missing",
    "internal_error",
];

const GENERIC = oauthFailureMessage("not-a-real-code");

describe("parseIntegrationReturn", () => {
    it("ignores URLs without a result", () => {
        expect(parseIntegrationReturn(new URLSearchParams("tab=connected"))).toBeNull();
        expect(parseIntegrationReturn(new URLSearchParams("integration_result=maybe"))).toBeNull();
    });

    it("reads a success with its connection and provider", () => {
        const params = new URLSearchParams(
            `integration_result=success&connection_id=${CONNECTION_ID}&provider=google-calendar`,
        );
        expect(parseIntegrationReturn(params)).toEqual({
            kind: "success",
            connectionId: CONNECTION_ID,
            provider: "google-calendar",
        });
    });

    it("rejects a success without a well-formed connection id", () => {
        for (const id of ["", "../admin", "123"]) {
            const params = new URLSearchParams({ integration_result: "success", connection_id: id });
            expect(parseIntegrationReturn(params)).toEqual({ kind: "error", reason: "invalid_return" });
        }
    });

    it("drops a malformed provider id", () => {
        const params = new URLSearchParams({
            integration_result: "success",
            connection_id: CONNECTION_ID,
            provider: "<script>",
        });
        expect(parseIntegrationReturn(params)).toMatchObject({ kind: "success", provider: null });
    });

    it("reads an error reason, defaulting to unknown", () => {
        expect(parseIntegrationReturn(new URLSearchParams("integration_result=error&reason=access_denied"))).toEqual({
            kind: "error",
            reason: "access_denied",
        });
        expect(parseIntegrationReturn(new URLSearchParams("integration_result=error"))).toEqual({
            kind: "error",
            reason: "unknown",
        });
    });
});

describe("urlWithoutReturnParams", () => {
    it("removes only the return parameters", () => {
        expect(
            urlWithoutReturnParams(
                `https://app.fallcha.ai/integrations?tab=connected&integration_result=success&connection_id=${CONNECTION_ID}&provider=google-calendar#top`,
            ),
        ).toBe("/integrations?tab=connected#top");
        expect(
            urlWithoutReturnParams("https://app.fallcha.ai/integrations?integration_result=error&reason=access_denied"),
        ).toBe("/integrations");
    });
});

describe("oauthFailureMessage", () => {
    it("has specific copy for every callback reason code", () => {
        const messages = CALLBACK_REASONS.map(oauthFailureMessage);
        for (const message of messages) expect(message).not.toBe(GENERIC);
        expect(new Set(messages).size).toBe(CALLBACK_REASONS.length);
    });

    it("never reflects the code itself", () => {
        expect(oauthFailureMessage("<b>evil</b>")).toBe(GENERIC);
        expect(GENERIC).not.toContain("not-a-real-code");
    });
});

describe("connection state and errors", () => {
    it("folds install state into the status", () => {
        expect(connectionState({ status: "active", credential_uuid: "c" })).toBe("active");
        expect(connectionState({ status: "active", credential_uuid: null })).toBe("not_installed");
        expect(connectionState({ status: "pending" })).toBe("pending");
        expect(connectionState({ status: "error", credential_uuid: "c" })).toBe("error");
        expect(connectionState({ status: "revoked" })).toBe("revoked");
    });

    it("maps error codes to friendly copy and falls back to last_error", () => {
        const revoked = connectionErrorMessage({ error_code: "grant_revoked", last_error: "invalid_grant" });
        expect(revoked).toMatch(/Reconnect/);
        expect(revoked).not.toContain("invalid_grant");
        expect(connectionErrorMessage({ error_code: "client_rejected" })).toMatch(/OAuth client/);
        expect(connectionErrorMessage({ error_code: "client_missing" })).toMatch(/removed/);
        expect(connectionErrorMessage({ last_error: "Calendar not shared with the service account" })).toBe(
            "Calendar not shared with the service account",
        );
        expect(connectionErrorMessage({})).toMatch(/Test the connection or reconnect/);
    });

    it("needs a reconnect only for errors with a code", () => {
        expect(needsReconnect({ status: "error", error_code: "grant_revoked" })).toBe(true);
        expect(needsReconnect({ status: "error", error_code: null })).toBe(false);
        expect(needsReconnect({ status: "active", error_code: "grant_revoked" })).toBe(false);
    });
});

describe("API errors", () => {
    it("recognises an unconfigured integrations backend", () => {
        expect(isUnavailableError({ detail: "x", code: "integration_unavailable" })).toBe(true);
        expect(isUnavailableError({ detail: "x", code: "tools_service_not_configured" })).toBe(true);
        expect(isUnavailableError({ detail: "x", code: "integration_conflict" })).toBe(false);
        expect(isUnavailableError(undefined)).toBe(false);
    });

    it("hides internal detail for unavailable services", () => {
        expect(
            integrationErrorMessage(
                { detail: "set TOOLS_SERVICE_URL and TOOLS_INTERNAL_SECRET", code: "tools_service_not_configured" },
                "fallback",
            ),
        ).toBe("Integrations aren't configured on this server.");
        expect(integrationErrorMessage({ detail: "x", code: "tools_service_unavailable" }, "fallback")).toMatch(
            /isn't responding/,
        );
        expect(integrationErrorMessage({ detail: "Calendar not found", code: "integration_invalid_request" }, "f")).toBe(
            "Calendar not found",
        );
        expect(integrationErrorMessage(undefined, "fallback")).toBe("fallback");
    });
});

describe("scopeLabel", () => {
    it("names known scopes and derives a label for others", () => {
        expect(scopeLabel("https://www.googleapis.com/auth/spreadsheets.readonly")).toBe(
            "Read Google Sheets (for order lookup)",
        );
        expect(scopeLabel("https://www.googleapis.com/auth/drive.file")).toBe("drive file");
    });
});
