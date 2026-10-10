// @vitest-environment node

import { describe, expect, it } from "vitest";

import {
    fieldsFromSchema,
    hasRequiredConfig,
    humanizeKey,
    initialValues,
    valuesToConfig,
} from "./schemaForm";

/** Trimmed copy of the Google Calendar provider's config_schema (Pydantic output). */
const CALENDAR_SCHEMA = {
    additionalProperties: false,
    title: "CalendarConfig",
    type: "object",
    required: ["calendar_id"],
    properties: {
        calendar_id: {
            description: "Google Calendar id, e.g. abc@group.calendar.google.com.",
            maxLength: 1024,
            minLength: 1,
            title: "Calendar Id",
            type: "string",
        },
        timezone: { default: "Europe/Dublin", title: "Timezone", type: "string" },
        booking_days: {
            default: [0, 1, 2, 3, 4],
            items: { maximum: 6, minimum: 0, type: "integer" },
            minItems: 1,
            title: "Booking Days",
            type: "array",
        },
        open_hour: { default: 9, maximum: 23, minimum: 0, title: "Open Hour", type: "integer" },
        orders_sheet_id: {
            anyOf: [{ maxLength: 256, type: "string" }, { type: "null" }],
            default: null,
            description: "Google Sheet id for read-only order lookup; unset disables it.",
            title: "Orders Sheet Id",
        },
        nested: { type: "object", properties: {} },
    },
};

describe("fieldsFromSchema", () => {
    it("maps supported properties in order and skips the rest", () => {
        const fields = fieldsFromSchema(CALENDAR_SCHEMA);
        expect(fields.map((f) => [f.key, f.kind])).toEqual([
            ["calendar_id", "string"],
            ["timezone", "string"],
            ["booking_days", "integer_array"],
            ["open_hour", "integer"],
            ["orders_sheet_id", "string"],
        ]);
    });

    it("reads required, nullable, limits and descriptions", () => {
        const byKey = Object.fromEntries(fieldsFromSchema(CALENDAR_SCHEMA).map((f) => [f.key, f]));
        expect(byKey.calendar_id).toMatchObject({ required: true, nullable: false, minLength: 1, label: "Calendar ID" });
        expect(byKey.orders_sheet_id).toMatchObject({
            required: false,
            nullable: true,
            maxLength: 256,
            description: "Google Sheet id for read-only order lookup; unset disables it.",
        });
        expect(byKey.booking_days).toMatchObject({ minimum: 0, maximum: 6, minItems: 1 });
        expect(byKey.open_hour).toMatchObject({ minimum: 0, maximum: 23, default: 9 });
    });

    it("supports booleans, enums, string arrays, enum arrays and $defs refs", () => {
        const fields = fieldsFromSchema({
            type: "object",
            properties: {
                enabled: { type: "boolean", default: true },
                mode: { $ref: "#/$defs/Mode" },
                tags: { type: "array", items: { type: "string" } },
                days: { type: "array", items: { enum: ["mon", "tue"] } },
                level: { anyOf: [{ $ref: "#/$defs/Level" }, { type: "null" }], default: null },
            },
            $defs: {
                Mode: { enum: ["fast", "slow"], type: "string" },
                Level: { enum: [1, 2, 3], type: "integer" },
            },
        });
        expect(fields.map((f) => [f.key, f.kind, f.options])).toEqual([
            ["enabled", "boolean", undefined],
            ["mode", "enum", ["fast", "slow"]],
            ["tags", "string_array", undefined],
            ["days", "enum_array", ["mon", "tue"]],
            ["level", "enum", [1, 2, 3]],
        ]);
        expect(fields.find((f) => f.key === "level")?.nullable).toBe(true);
    });

    it("returns nothing for missing or malformed schemas", () => {
        expect(fieldsFromSchema(null)).toEqual([]);
        expect(fieldsFromSchema(undefined)).toEqual([]);
        expect(fieldsFromSchema({ type: "object" })).toEqual([]);
        expect(fieldsFromSchema([1, 2])).toEqual([]);
    });
});

describe("hasRequiredConfig", () => {
    it("is true only when a field is required", () => {
        expect(hasRequiredConfig(CALENDAR_SCHEMA)).toBe(true);
        expect(hasRequiredConfig({ type: "object", properties: { a: { type: "string" } } })).toBe(false);
        expect(hasRequiredConfig(null)).toBe(false);
    });
});

describe("initialValues", () => {
    const fields = fieldsFromSchema(CALENDAR_SCHEMA);

    it("uses schema defaults, rendering arrays as comma-separated text", () => {
        expect(initialValues(fields)).toEqual({
            calendar_id: "",
            timezone: "Europe/Dublin",
            booking_days: "0, 1, 2, 3, 4",
            open_hour: "9",
            orders_sheet_id: "",
        });
    });

    it("prefers the connection's current config", () => {
        const values = initialValues(fields, { calendar_id: "primary", booking_days: [1, 3], open_hour: 8 });
        expect(values).toMatchObject({ calendar_id: "primary", booking_days: "1, 3", open_hour: "8" });
    });
});

describe("valuesToConfig", () => {
    const fields = fieldsFromSchema(CALENDAR_SCHEMA);

    it("converts types, omits empty optionals and nulls empty nullables", () => {
        const { config, errors } = valuesToConfig(fields, {
            calendar_id: "  team@group.calendar.google.com ",
            timezone: "",
            booking_days: "0, 2,4",
            open_hour: "10",
            orders_sheet_id: "",
        });
        expect(errors).toEqual({});
        expect(config).toEqual({
            calendar_id: "team@group.calendar.google.com",
            booking_days: [0, 2, 4],
            open_hour: 10,
            orders_sheet_id: null,
        });
    });

    it("reports required, type and range errors per field", () => {
        const { errors } = valuesToConfig(fields, {
            calendar_id: " ",
            timezone: "x",
            booking_days: "1, 9",
            open_hour: "9.5",
            orders_sheet_id: "",
        });
        expect(errors).toEqual({
            calendar_id: "Required",
            booking_days: "9: must be at most 6",
            open_hour: "Enter a whole number",
        });
    });

    it("validates enums, booleans, enum arrays and string limits", () => {
        const custom = fieldsFromSchema({
            type: "object",
            required: ["mode"],
            properties: {
                mode: { enum: ["fast", "slow"] },
                level: { enum: [1, 2] },
                on: { type: "boolean" },
                days: { type: "array", items: { enum: ["mon", "tue"] }, minItems: 1 },
                code: { type: "string", maxLength: 3 },
                tags: { type: "array", items: { type: "string" } },
            },
        });
        expect(
            valuesToConfig(custom, { mode: "slow", level: "2", on: true, days: ["tue"], code: "abc", tags: "a, b ,," }),
        ).toEqual({
            config: { mode: "slow", level: 2, on: true, days: ["tue"], code: "abc", tags: ["a", "b"] },
            errors: {},
        });
        expect(valuesToConfig(custom, { mode: "other", on: false, days: [], code: "abcd" }).errors).toEqual({
            mode: "Choose one of the options",
            days: "Choose at least 1",
            code: "Must be at most 3 characters",
        });
    });
});

describe("humanizeKey", () => {
    it("sentence-cases keys and upper-cases acronyms", () => {
        expect(humanizeKey("calendar_id")).toBe("Calendar ID");
        expect(humanizeKey("max_slots_returned")).toBe("Max slots returned");
        expect(humanizeKey("api_base_url")).toBe("API base URL");
    });
});
