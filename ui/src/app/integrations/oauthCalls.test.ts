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

    it("accepts Calendly's sign-in page and nothing like it", () => {
        expect(isTrustedAuthorizationUrl("https://auth.calendly.com/oauth/authorize?state=x")).toBe(true);
        expect(isTrustedAuthorizationUrl("https://auth.calendly.com.evil.example/oauth/authorize")).toBe(false);
        expect(isTrustedAuthorizationUrl("https://calendly.com/oauth/authorize")).toBe(false);
    });

    it("accepts Microsoft's sign-in page and nothing like it", () => {
        expect(
            isTrustedAuthorizationUrl("https://login.microsoftonline.com/common/oauth2/v2.0/authorize?state=x"),
        ).toBe(true);
        expect(isTrustedAuthorizationUrl("https://login.microsoftonline.com.evil.example/common")).toBe(false);
        expect(isTrustedAuthorizationUrl("https://login.live.com/oauth20_authorize.srf")).toBe(false);
    });

    it("accepts a provider-declared host", () => {
        expect(isTrustedAuthorizationUrl("https://login.example.com/auth", ["login.example.com"])).toBe(true);
    });
});
