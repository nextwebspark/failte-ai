// @vitest-environment node

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { DEFAULT_TRANSFER_CALL_CONFIG, getCategoryConfig } from "./config";

describe("transfer introduction defaults", () => {
    it("matches the backend defaults published in OpenAPI", () => {
        const schema = JSON.parse(readFileSync(
            resolve(process.cwd(), "../docs/api-reference/openapi.json"),
            "utf8",
        )).components.schemas.TransferCallConfig.properties;

        expect(DEFAULT_TRANSFER_CALL_CONFIG.introduction_prompt)
            .toBe(schema.introduction_prompt.default);
        expect(DEFAULT_TRANSFER_CALL_CONFIG.introduction_enabled)
            .toBe(schema.introduction_enabled.default);
    });
});

describe("tool categories", () => {
    it("routes the integration category to the integrations page", () => {
        const integration = getCategoryConfig("integration");
        expect(integration?.disabled).toBeFalsy();
        expect(integration?.href).toBe("/integrations");
    });

    it("keeps native tools disabled", () => {
        expect(getCategoryConfig("native")?.disabled).toBe(true);
    });
});
