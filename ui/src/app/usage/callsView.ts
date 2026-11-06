import { endOfDay, startOfDay, subDays } from "date-fns";

import type { ActiveFilter, DateRangeValue, FilterAttribute, MultiSelectValue, TextValue } from "@/types/filters";

/** The filters the simple search sets; everything else lives under More. */
export const QUICK_FILTER_IDS = ["callerNumber", "dateRange", "dispositionCode"] as const;

export type QuickWhen = "any" | "today" | "last7" | "last30" | "custom";

export const WHEN_OPTIONS: { value: Exclude<QuickWhen, "custom">; label: string }[] = [
    { value: "any", label: "Any time" },
    { value: "today", label: "Today" },
    { value: "last7", label: "Last 7 days" },
    { value: "last30", label: "Last 30 days" },
];

export interface QuickSearch {
    phone: string;
    when: QuickWhen;
    /** A disposition code, or "any". */
    outcome: string;
}

export const EMPTY_QUICK_SEARCH: QuickSearch = { phone: "", when: "any", outcome: "any" };

/**
 * The digits to look for in a stored number. Callers type "087 123 4567" or
 * "+353 87 123 4567" while numbers are stored as "+353871234567", and the API
 * matches a substring, so drop the spacing and the leading trunk zero.
 */
export function phoneSearchDigits(input: string): string {
    const digits = input.replace(/\D/g, "");
    if (digits.startsWith("00")) return digits.slice(2);
    return digits.replace(/^0+/, "");
}

function whenRange(when: QuickWhen, now: Date): DateRangeValue | null {
    switch (when) {
        case "today":
            return { from: startOfDay(now), to: endOfDay(now) };
        case "last7":
            return { from: startOfDay(subDays(now, 6)), to: endOfDay(now) };
        case "last30":
            return { from: startOfDay(subDays(now, 29)), to: endOfDay(now) };
        default:
            return null;
    }
}

/**
 * The full filter list after a simple search: the advanced filters as they
 * are, with the phone, date and outcome filters replaced by the search's.
 * "custom" keeps a date range set under More as it is.
 */
export function applyQuickSearch(
    current: ActiveFilter[],
    search: QuickSearch,
    attributes: FilterAttribute[],
    now: Date,
): ActiveFilter[] {
    const attribute = (id: string) => attributes.find((a) => a.id === id);
    const keep = current.filter(
        (f) =>
            !(QUICK_FILTER_IDS as readonly string[]).includes(f.attribute.id) ||
            (search.when === "custom" && f.attribute.id === "dateRange"),
    );
    const next = [...keep];

    const digits = phoneSearchDigits(search.phone);
    const phoneAttr = attribute("callerNumber");
    if (digits && phoneAttr) {
        next.push({ attribute: phoneAttr, value: { value: digits } satisfies TextValue, isValid: true });
    }

    const range = whenRange(search.when, now);
    const dateAttr = attribute("dateRange");
    if (range && dateAttr) next.push({ attribute: dateAttr, value: range, isValid: true });

    const outcomeAttr = attribute("dispositionCode");
    if (search.outcome !== "any" && outcomeAttr) {
        next.push({
            attribute: outcomeAttr,
            value: { codes: [search.outcome] } satisfies MultiSelectValue,
            isValid: true,
        });
    }
    return next;
}

/** What the simple search shows for the filters in force (from the URL, or set under More). */
export function quickSearchFrom(filters: ActiveFilter[]): QuickSearch {
    const find = (id: string) => filters.find((f) => f.attribute.id === id);
    const phone = (find("callerNumber")?.value as TextValue | undefined)?.value ?? "";
    const codes = (find("dispositionCode")?.value as MultiSelectValue | undefined)?.codes ?? [];
    return {
        phone,
        // A date range can't be told apart from a preset after a reload: show it as set.
        when: find("dateRange") ? "custom" : "any",
        outcome: codes.length === 1 ? codes[0] : "any",
    };
}

/** True when filters other than the simple search's are in force. */
export function hasAdvancedFilters(filters: ActiveFilter[]): boolean {
    return filters.some(
        (f) =>
            !(QUICK_FILTER_IDS as readonly string[]).includes(f.attribute.id) ||
            (f.attribute.id === "dispositionCode" &&
                ((f.value as MultiSelectValue).codes?.length ?? 0) > 1),
    );
}

/**
 * A readable outcome: "do_not_call" → "Do not call". Short all-capital codes a
 * business chose itself ("XFER") are left as they are.
 */
export function outcomeLabel(code: string): string {
    if (/^[A-Z0-9_]+$/.test(code) && code.length <= 6) return code;
    const words = code.replace(/[_-]+/g, " ").trim().toLowerCase();
    return words.charAt(0).toUpperCase() + words.slice(1);
}

/** "3m 5s", "45s", "2m". */
export function formatDuration(seconds: number): string {
    const minutes = Math.floor(seconds / 60);
    const rest = Math.round(seconds % 60);
    if (minutes === 0) return `${rest}s`;
    if (rest === 0) return `${minutes}m`;
    return `${minutes}m ${rest}s`;
}

/**
 * "Fri 6 Nov 2026, 13:12" in the workspace's time zone: Irish/UK order and a
 * 24-hour clock, as an owner reads a call log.
 */
export function formatCallTime(value: string, timezone?: string | null): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    const options: Intl.DateTimeFormatOptions = {
        weekday: "short",
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
    };
    try {
        return date.toLocaleString("en-IE", { ...options, timeZone: timezone || undefined });
    } catch {
        // An unknown zone name: the browser's own zone is better than nothing.
        return date.toLocaleString("en-IE", options);
    }
}
