// @vitest-environment node

import { describe, expect, it } from "vitest";

import { choiceKeys, chosenLabel, hasChoices, needsChoice } from "./choices";
import { authModeLabel, scopeLabel } from "./messages";
import { fieldsFromSchema } from "./schemaForm";
import { tokenProblem } from "./TokenConnect";

/** The Calendly provider's config schema, as the catalog publishes it. */
const CALENDLY_SCHEMA = {
    type: "object",
    properties: {
        event_type: { anyOf: [{ type: "string" }, { type: "null" }], default: null, "x-fallcha-choice": "value" },
        event_type_name: { anyOf: [{ type: "string" }, { type: "null" }], default: null, "x-fallcha-choice": "label" },
        timezone: { anyOf: [{ type: "string" }, { type: "null" }], default: null },
        ai_booking_enabled: { type: "boolean", default: true },
        horizon_days: { type: "integer", default: 14, minimum: 1, maximum: 60 },
    },
};
const CALENDLY = { capabilities: ["bookings", "choices"], config_schema: CALENDLY_SCHEMA };
const EVENT = "https://api.calendly.com/event_types/ET-1";

describe("settings picked from the provider's list", () => {
    it("finds the picked value's field and its name's field", () => {
        expect(choiceKeys(CALENDLY_SCHEMA)).toEqual({ value: "event_type", label: "event_type_name" });
        expect(choiceKeys({ properties: { calendar_id: { type: "string" } } })).toBeNull();
        expect(choiceKeys(null)).toBeNull();
    });

    it("leaves picked fields out of the typed settings form", () => {
        expect(fieldsFromSchema(CALENDLY_SCHEMA).map((f) => f.key)).toEqual([
            "timezone",
            "ai_booking_enabled",
            "horizon_days",
        ]);
    });

    it("says what was picked, or that nothing is yet", () => {
        expect(hasChoices(CALENDLY)).toBe(true);
        expect(hasChoices({ capabilities: ["bookings"], config_schema: CALENDLY_SCHEMA })).toBe(false);
        expect(needsChoice(CALENDLY, { config: {} })).toBe(true);
        expect(needsChoice(CALENDLY, { config: { event_type: null } })).toBe(true);
        expect(chosenLabel(CALENDLY, { config: { event_type: EVENT, event_type_name: "Consultation" } })).toBe(
            "Consultation",
        );
        expect(chosenLabel(CALENDLY, { config: { event_type: EVENT } })).toBe(EVENT);
        expect(needsChoice(CALENDLY, { config: { event_type: EVENT } })).toBe(false);
        // Google Calendar has nothing to pick.
        expect(needsChoice({ capabilities: ["bookings"], config_schema: {} }, { config: {} })).toBe(false);
    });
});

describe("Calendly wording", () => {
    it("calls the token what Calendly calls it", () => {
        expect(authModeLabel("api_key", "calendly")).toBe("Personal access token");
        expect(authModeLabel("api_key")).toBe("API key");
        expect(authModeLabel("oauth2", "calendly")).toBe("Sign in with your account");
    });

    it("explains Calendly's permissions in plain words", () => {
        expect(scopeLabel("scheduled_events:write")).toBe("Book meetings for callers");
        expect(scopeLabel("availability:read")).toBe("See your free times");
    });

    it("checks a pasted token's shape before sending it", () => {
        expect(tokenProblem("")).toBe("Paste your token.");
        expect(tokenProblem("abc def ghi jkl mno pqr")).toMatch(/no spaces/);
        expect(tokenProblem("short")).toMatch(/too short/);
        expect(tokenProblem("  eyJraWQiOiIxY2UxZTEzNjE3ZGNmNzY2YjNjZWJjY2Y4ZGM1YmFmYThhNjVlNjg0  ")).toBeNull();
    });
});
