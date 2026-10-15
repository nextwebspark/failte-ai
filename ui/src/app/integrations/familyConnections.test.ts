// @vitest-environment node

import { describe, expect, it } from "vitest";

import type { IntegrationConnectionResponse, IntegrationProvider } from "@/client/types.gen";

import { familyConnections } from "./ConnectDialog";

function provider(id: string, auth_family: string | null): IntegrationProvider {
    return {
        id,
        title: id,
        description: "",
        icon: "",
        auth_family,
        auth_modes: ["service_account", "oauth2"],
        scopes: [],
        tools: [],
    };
}

const CALENDAR = provider("google-calendar", "google");
const SHEETS = provider("google-sheets", "google");
const ECHO = provider("echo", null);
const PROVIDERS = [CALENDAR, SHEETS, ECHO];

function conn(overrides: Partial<IntegrationConnectionResponse>): IntegrationConnectionResponse {
    return {
        id: "c1",
        provider: CALENDAR.id,
        auth_mode: "service_account",
        account_label: "sa@acme.iam.gserviceaccount.com",
        status: "active",
        created_at: "",
        updated_at: "",
        ...overrides,
    };
}

describe("familyConnections", () => {
    it("offers active same-family connections of the same auth mode, once per account", () => {
        const found = familyConnections(
            SHEETS,
            PROVIDERS,
            [
                conn({ id: "a" }),
                conn({ id: "dup", provider: SHEETS.id }), // same account again
                conn({ id: "err", account_label: "x@y.z", status: "error" }),
                conn({ id: "revoked", account_label: "r@y.z", status: "revoked" }),
                conn({ id: "oauth", auth_mode: "oauth2", account_label: "alice@acme.test" }),
                conn({ id: "other-family", provider: ECHO.id, account_label: "echo@x.y" }),
                conn({ id: "nolabel", account_label: null }),
                conn({ id: "unknown", provider: "gone", account_label: "g@x.y" }),
            ],
            "service_account",
        );
        expect(found).toEqual([{ connectionId: "a", label: "sa@acme.iam.gserviceaccount.com" }]);
    });

    it("finds OAuth accounts separately", () => {
        const found = familyConnections(
            SHEETS,
            PROVIDERS,
            [conn({ id: "oauth", auth_mode: "oauth2", account_label: "alice@acme.test" })],
            "oauth2",
        );
        expect(found).toEqual([{ connectionId: "oauth", label: "alice@acme.test" }]);
    });

    it("treats a provider without a family as its own family", () => {
        expect(familyConnections(ECHO, PROVIDERS, [conn({ id: "a" })], "service_account")).toEqual([]);
    });
});
