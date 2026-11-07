import { describe, expect, it } from "vitest";

import {
    attachedToolUuids,
    bookingLine,
    bookingTimesByDay,
    calendarProvider,
    clockLabel,
    fillGreeting,
    isCalendarTool,
    startGreeting,
} from "./knowledge";

const DEFINITION = {
    nodes: [
        {
            type: "startCall",
            data: { is_start: true, greeting_type: "text", greeting: "Hello, {{initial_context.business_name}}.", tool_uuids: ["t1"] },
        },
        { type: "agentNode", data: { tool_uuids: ["t1", "t2"] } },
        { type: "endCall", data: {} },
    ],
};

describe("what the agent's definition says", () => {
    it("collects every tool its steps use", () => {
        expect([...attachedToolUuids(DEFINITION)]).toEqual(["t1", "t2"]);
        expect(attachedToolUuids(null).size).toBe(0);
    });

    it("finds the first thing callers hear", () => {
        expect(startGreeting(DEFINITION)).toEqual({ kind: "text", text: "Hello, {{initial_context.business_name}}." });
        expect(
            startGreeting({ nodes: [{ type: "startCall", data: { greeting_type: "audio", greeting_recording_id: "r1" } }] }),
        ).toEqual({ kind: "recording" });
        expect(startGreeting({ nodes: [{ type: "startCall", data: {} }] })).toBeNull();
    });

    it("fills the greeting from the facts, dropping empty ones cleanly", () => {
        expect(fillGreeting("Hello, {{ initial_context.business_name }}.", { business_name: "Bia" })).toBe("Hello, Bia.");
        expect(fillGreeting("Hello {{initial_context.missing}}, how can I help?", {})).toBe("Hello, how can I help?");
    });

    it("recognises the Google Calendar tool by its address", () => {
        expect(isCalendarTool({ category: "mcp", definition: { config: { url: "https://x/mcp/google-calendar" } } })).toBe(true);
        expect(isCalendarTool({ category: "mcp", definition: { config: { url: "https://x/mcp/hubspot" } } })).toBe(false);
        expect(isCalendarTool({ category: "transfer_call", definition: {} })).toBe(false);
    });

    it("tells Calendly from Google Calendar", () => {
        const tool = (url: string) => ({ category: "mcp", definition: { config: { url } } });
        expect(calendarProvider(tool("https://tools.example/mcp/calendly"))).toBe("calendly");
        expect(calendarProvider(tool("https://tools.example/mcp/calendly/"))).toBe("calendly");
        expect(calendarProvider(tool("https://x/mcp/google-calendar"))).toBe("google-calendar");
        expect(calendarProvider(tool("https://x/mcp/calendly-lookalike"))).toBeNull();
        expect(isCalendarTool(tool("https://tools.example/mcp/calendly"))).toBe(true);
        expect(bookingLine("calendly")).toBe("Checks free times in your Calendly and books them.");
        expect(bookingLine("google-calendar")).toBe("Checks free times in your Google Calendar and books them.");
    });
});

describe("booking times", () => {
    it("reads clock times the Irish/UK way", () => {
        expect(clockLabel("17:00")).toBe("5 pm");
        expect(clockLabel("12:30")).toBe("12:30 pm");
        expect(clockLabel("00:00")).toBe("12 am");
    });

    it("lays the calendar's periods out by weekday, Monday first", () => {
        const days = bookingTimesByDay({
            service_periods: [
                { days: [1, 2, 3, 4, 5, 6], first_start: "17:00", last_start: "21:00" },
                { days: [5, 6], first_start: "12:00", last_start: "14:30" },
            ],
        });
        expect(days?.[0]).toEqual([]);
        expect(days?.[1]).toEqual(["5 pm–9 pm"]);
        expect(days?.[5]).toEqual(["12 pm–2:30 pm", "5 pm–9 pm"]);
    });

    it("is null without stored periods", () => {
        expect(bookingTimesByDay({})).toBeNull();
        expect(bookingTimesByDay(null)).toBeNull();
        expect(bookingTimesByDay({ service_periods: [{ days: [9], first_start: "x", last_start: "y" }] })).toBeNull();
    });
});
