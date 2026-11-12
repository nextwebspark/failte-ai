import { describe, expect, it } from "vitest";

import { toolResultSummary } from "./toolSummary";

describe("toolResultSummary", () => {
    it("summarises a verified order lookup from an HTTP tool result", () => {
        const result = {
            status: "success",
            status_code: 200,
            data: {
                lookup: "order",
                verified: true,
                status: "Dispatched",
                status_date: "2026-11-07",
                courier: "Courier",
                tracking_ending: "4F2K",
                delivery_town: "Galway",
            },
        };
        expect(toolResultSummary(result)).toBe("Order lookup · verified · Dispatched 7 Nov · Courier ••4F2K");
    });

    it("reads a JSON string result and an expected date", () => {
        const result = JSON.stringify({
            data: { lookup: "order", verified: true, status: "Back-ordered", status_date: "2026-11-01", expected_date: "2026-11-17" },
        });
        expect(toolResultSummary(result)).toBe("Order lookup · verified · Back-ordered 1 Nov · expected 17 Nov");
    });

    it("says only that it couldn't verify, with no detail", () => {
        expect(toolResultSummary({ data: { lookup: "order", verified: false, say: "..." } })).toBe("Order lookup · couldn't verify");
        expect(toolResultSummary({ data: { lookup: "order", verified: false, locked: true } })).toBe(
            "Order lookup · couldn't verify · stopped trying",
        );
    });

    it("ignores other tools", () => {
        expect(toolResultSummary({ chunks: [] })).toBeNull();
        expect(toolResultSummary("not json")).toBeNull();
        expect(toolResultSummary(undefined)).toBeNull();
    });
});
