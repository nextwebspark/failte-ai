import { describe, expect, it } from "vitest";

import { addressTypeLabel, credentialLabel, humanizeKey, pointsAtLocalhost, usesInboundWebhook } from "./display";

describe("phone account display", () => {
    it("uses the provider form's labels, then a readable fallback", () => {
        expect(credentialLabel("ari_endpoint", { ari_endpoint: "ARI Endpoint" })).toBe("ARI Endpoint");
        expect(credentialLabel("ws_client_name", {})).toBe("Ws client name");
        expect(humanizeKey("dial_string_template")).toBe("Dial string template");
    });

    it("names number types plainly", () => {
        expect(addressTypeLabel("sip_extension")).toBe("SIP extension");
        expect(addressTypeLabel("pstn")).toBe("Phone number");
        expect(addressTypeLabel("sip_uri")).toBe("SIP address");
    });

    it("spots ARI addresses on localhost", () => {
        expect(pointsAtLocalhost("http://localhost:8088")).toBe(true);
        expect(pointsAtLocalhost("http://127.0.0.1:8088/ari")).toBe(true);
        expect(pointsAtLocalhost("http://host.docker.internal:8088")).toBe(false);
        expect(pointsAtLocalhost("https://pbx.example.ie:8089")).toBe(false);
        expect(pointsAtLocalhost("not a url")).toBe(false);
        expect(pointsAtLocalhost(undefined)).toBe(false);
    });

    it("shows the inbound webhook only for providers that call us over HTTP", () => {
        expect(usesInboundWebhook("twilio")).toBe(true);
        expect(usesInboundWebhook("ari")).toBe(false);
    });
});
