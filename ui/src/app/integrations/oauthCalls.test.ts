// @vitest-environment node

import { describe, expect, it } from "vitest";

import { isTrustedAuthorizationUrl } from "./oauthCalls";

describe("isTrustedAuthorizationUrl", () => {
    it("accepts https Google sign-in URLs", () => {
        expect(isTrustedAuthorizationUrl("https://accounts.google.com/o/oauth2/v2/auth?state=x")).toBe(true);
    });

    it.each([
        "http://accounts.google.com/o/oauth2/v2/auth",
        "https://accounts.google.com:8443/auth",
        "https://accounts.google.com.evil.example/auth",
        "https://evil.example/?https://accounts.google.com",
        "https://user:pw@accounts.google.com/auth",
        "javascript:alert(1)",
        "/relative",
        "",
    ])("rejects %s", (url) => {
        expect(isTrustedAuthorizationUrl(url)).toBe(false);
    });

    it("accepts a provider-declared host", () => {
        expect(isTrustedAuthorizationUrl("https://login.example.com/auth", ["login.example.com"])).toBe(true);
    });
});
