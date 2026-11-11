import { describe, expect, it } from "vitest";

import {
    apiFilters,
    DEFAULT_FOLLOW_UPS_QUERY,
    followUpsQueryFromParams,
    followUpsQueryToParams,
    isNarrowed,
    whenLabel,
} from "./followUpsQuery";

describe("Follow-ups controls in the URL", () => {
    it("leaves the defaults out", () => {
        expect(followUpsQueryToParams(DEFAULT_FOLLOW_UPS_QUERY).toString()).toBe("");
        expect(followUpsQueryFromParams(new URLSearchParams())).toEqual(DEFAULT_FOLLOW_UPS_QUERY);
    });

    it("round-trips every control", () => {
        const query = {
            status: "all" as const,
            when: "custom" as const,
            start: "2026-11-02",
            end: "2026-11-04",
            kind: "time_was_full" as const,
            q: "Saturday",
        };
        const params = followUpsQueryToParams(query);
        expect(params.toString()).toBe("status=all&when=custom&start=2026-11-02&end=2026-11-04&kind=time_was_full&q=Saturday");
        expect(followUpsQueryFromParams(params)).toEqual(query);
    });

    it("ignores what it doesn't know", () => {
        const query = followUpsQueryFromParams(new URLSearchParams("status=maybe&when=90d&kind=nope&when2=x"));
        expect(query).toEqual(DEFAULT_FOLLOW_UPS_QUERY);
        // Picked days without a valid start fall back to the whole window.
        expect(followUpsQueryFromParams(new URLSearchParams("when=custom&start=soon")).when).toBe("30d");
    });

    it("asks the API for the whole window by default, and for picked days as dates", () => {
        expect(apiFilters(DEFAULT_FOLLOW_UPS_QUERY)).toEqual({ range: null, kind: null, q: "" });
        expect(apiFilters({ ...DEFAULT_FOLLOW_UPS_QUERY, when: "today" }).range).toBe("today");
        expect(apiFilters({ ...DEFAULT_FOLLOW_UPS_QUERY, when: "custom", start: "2026-11-02", end: null })).toEqual({
            start_date: "2026-11-02",
            end_date: "2026-11-02",
            kind: null,
            q: "",
        });
    });

    it("knows when the list is narrowed, and names the dates", () => {
        expect(isNarrowed(DEFAULT_FOLLOW_UPS_QUERY)).toBe(false);
        expect(isNarrowed({ ...DEFAULT_FOLLOW_UPS_QUERY, status: "done" })).toBe(false);
        expect(isNarrowed({ ...DEFAULT_FOLLOW_UPS_QUERY, q: "  x " })).toBe(true);
        expect(whenLabel({ when: "7d", start: null, end: null })).toBe("Last 7 days");
        expect(whenLabel({ when: "custom", start: "2026-11-02", end: "2026-11-04" })).toBe("2 Nov – 4 Nov");
    });
});
