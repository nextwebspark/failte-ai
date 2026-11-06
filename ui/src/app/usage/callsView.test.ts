import { describe, expect, it } from "vitest";

import { getUsageFilterAttributes } from "@/lib/filterAttributes";
import type { ActiveFilter, DateRangeValue } from "@/types/filters";

import {
    applyQuickSearch,
    EMPTY_QUICK_SEARCH,
    formatDuration,
    hasAdvancedFilters,
    outcomeLabel,
    phoneSearchDigits,
    quickSearchFrom,
} from "./callsView";

const ATTRS = getUsageFilterAttributes(false);
const attr = (id: string) => ATTRS.find((a) => a.id === id)!;
const NOW = new Date(2026, 10, 6, 15, 0);

describe("phoneSearchDigits", () => {
    it("matches however the number was typed", () => {
        expect(phoneSearchDigits("087 123 4567")).toBe("871234567");
        expect(phoneSearchDigits("+353 (87) 123-4567")).toBe("353871234567");
        expect(phoneSearchDigits("00353871234567")).toBe("353871234567");
        expect(phoneSearchDigits("  ")).toBe("");
    });
});

describe("applyQuickSearch", () => {
    it("builds phone, date and outcome filters", () => {
        const next = applyQuickSearch([], { phone: "087 123", when: "last7", outcome: "XFER" }, ATTRS, NOW);
        expect(next.map((f) => f.attribute.id)).toEqual(["callerNumber", "dateRange", "dispositionCode"]);
        expect(next[0].value).toEqual({ value: "87123" });
        const range = next[1].value as DateRangeValue;
        expect(range.from).toEqual(new Date(2026, 9, 31));
        expect(range.to?.getDate()).toBe(6);
        expect(next[2].value).toEqual({ codes: ["XFER"] });
    });

    it("keeps advanced filters and replaces the simple ones", () => {
        const duration: ActiveFilter = { attribute: attr("duration"), value: { min: 60, max: 300 }, isValid: true };
        const oldPhone: ActiveFilter = { attribute: attr("callerNumber"), value: { value: "111" }, isValid: true };
        const next = applyQuickSearch([duration, oldPhone], EMPTY_QUICK_SEARCH, ATTRS, NOW);
        expect(next).toEqual([duration]);
    });

    it("leaves a date range set under More alone", () => {
        const range: ActiveFilter = { attribute: attr("dateRange"), value: { from: NOW, to: NOW }, isValid: true };
        const next = applyQuickSearch([range], { ...EMPTY_QUICK_SEARCH, when: "custom" }, ATTRS, NOW);
        expect(next).toEqual([range]);
    });
});

describe("quickSearchFrom / hasAdvancedFilters", () => {
    it("reads the simple search back from the filters in force", () => {
        const filters = applyQuickSearch([], { phone: "871", when: "today", outcome: "XFER" }, ATTRS, NOW);
        expect(quickSearchFrom(filters)).toEqual({ phone: "871", when: "custom", outcome: "XFER" });
        expect(hasAdvancedFilters(filters)).toBe(false);
    });

    it("opens More when expert filters are in force", () => {
        expect(
            hasAdvancedFilters([{ attribute: attr("duration"), value: { min: 1, max: 2 }, isValid: true }]),
        ).toBe(true);
        expect(
            hasAdvancedFilters([
                { attribute: attr("dispositionCode"), value: { codes: ["A", "B"] }, isValid: true },
            ]),
        ).toBe(true);
    });
});

describe("labels", () => {
    it("reads outcome codes as words", () => {
        expect(outcomeLabel("callback_requested")).toBe("Callback requested");
        expect(outcomeLabel("no-answer")).toBe("No answer");
        expect(outcomeLabel("XFER")).toBe("XFER");
        expect(outcomeLabel("INFO_GIVEN")).toBe("Info given");
    });

    it("formats call length", () => {
        expect(formatDuration(45)).toBe("45s");
        expect(formatDuration(120)).toBe("2m");
        expect(formatDuration(185)).toBe("3m 5s");
    });
});
