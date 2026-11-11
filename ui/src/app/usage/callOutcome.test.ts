import { describe, expect, it } from "vitest";

import type { CallResult } from "@/client/types.gen";
import { RESULT_WORDS } from "@/components/dashboard/dashboardView";

import { callResultChip } from "./callOutcome";

describe("A call's outcome on Calls", () => {
    it("uses the API's result, in Home's words, not the stored ending code", () => {
        // The engine wrote "end_call" ("Call finished") on both; Home reads one
        // as a booking and the other as handled by the agent. So does Calls.
        const booked = { result: "booking_made" as const, disposition: "end_call", gathered_context: { mapped_call_disposition: "end_call" } };
        const ordinary = { result: "handled" as const, disposition: "end_call", gathered_context: { mapped_call_disposition: "end_call" } };
        expect(callResultChip(booked)).toEqual({ label: "Booking made", tone: "brand" });
        expect(callResultChip(ordinary)).toEqual({ label: "Handled by your agent", tone: "brand" });
    });

    it("matches Home for every result", () => {
        for (const result of Object.keys(RESULT_WORDS) as CallResult[]) {
            expect(callResultChip({ result, disposition: "end_call" })).toEqual(RESULT_WORDS[result]);
        }
    });

    it("falls back to the stored code, in Home's colours, without a result", () => {
        expect(callResultChip({ disposition: "callback_requested", gathered_context: {} })).toEqual({
            label: "Callback requested",
            tone: "amber",
        });
        expect(callResultChip({ disposition: null, gathered_context: null })).toEqual({ label: "Not recorded", tone: "neutral" });
    });
});
