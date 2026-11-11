import type { DashboardRange, FollowUpKind, FollowUpStatus } from "@/client/types.gen";
import { FOLLOW_UP_KINDS } from "@/components/dashboard/dashboardView";
import type { FollowUpFilters } from "@/components/dashboard/useDashboardData";

/*
 * The Follow-ups page's controls, kept in the URL so a refresh, Back and a
 * shared link show the same list. Defaults are left out of the URL.
 */

/** "30d" is the whole Follow-ups window (calls from the last 30 days raise follow-ups). */
export type FollowUpsWhen = DashboardRange | "custom";

export interface FollowUpsQuery {
    status: FollowUpStatus;
    when: FollowUpsWhen;
    /** "yyyy-mm-dd", only with when = "custom". */
    start: string | null;
    end: string | null;
    kind: FollowUpKind | null;
    q: string;
}

export const DEFAULT_FOLLOW_UPS_QUERY: FollowUpsQuery = {
    status: "open",
    when: "30d",
    start: null,
    end: null,
    kind: null,
    q: "",
};

export const STATUS_OPTIONS: { value: FollowUpStatus; label: string }[] = [
    { value: "open", label: "To do" },
    { value: "done", label: "Done" },
    { value: "all", label: "All" },
];

export const WHEN_OPTIONS: { value: DashboardRange; label: string }[] = [
    { value: "today", label: "Today" },
    { value: "7d", label: "Last 7 days" },
    { value: "30d", label: "Last 30 days" },
];

/** How far back the days picker goes: the Follow-ups window. */
export const WINDOW_DAYS = 30;

const DAY = /^\d{4}-\d{2}-\d{2}$/;

export function followUpsQueryFromParams(params: URLSearchParams): FollowUpsQuery {
    const status = params.get("status");
    const when = params.get("when");
    const kind = params.get("kind");
    const start = params.get("start");
    const end = params.get("end");
    const custom = when === "custom" && start !== null && DAY.test(start);
    return {
        status: status === "done" || status === "all" ? status : "open",
        when: custom ? "custom" : when === "today" || when === "7d" ? when : "30d",
        start: custom ? start : null,
        end: custom && end && DAY.test(end) ? end : null,
        kind: FOLLOW_UP_KINDS.includes(kind as FollowUpKind) ? (kind as FollowUpKind) : null,
        q: params.get("q") ?? "",
    };
}

export function followUpsQueryToParams(query: FollowUpsQuery): URLSearchParams {
    const params = new URLSearchParams();
    if (query.status !== "open") params.set("status", query.status);
    if (query.when === "custom" && query.start) {
        params.set("when", "custom");
        params.set("start", query.start);
        if (query.end && query.end !== query.start) params.set("end", query.end);
    } else if (query.when !== "30d") {
        params.set("when", query.when);
    }
    if (query.kind) params.set("kind", query.kind);
    if (query.q.trim()) params.set("q", query.q.trim());
    return params;
}

/** The filters the API takes (the tab is sent on its own). */
export function apiFilters(query: FollowUpsQuery): FollowUpFilters {
    if (query.when === "custom" && query.start) {
        return { start_date: query.start, end_date: query.end ?? query.start, kind: query.kind, q: query.q };
    }
    return { range: query.when === "30d" || query.when === "custom" ? null : query.when, kind: query.kind, q: query.q };
}

/** Whether anything narrows the list beyond the tab (dates, kind or search). */
export function isNarrowed(query: FollowUpsQuery): boolean {
    return query.when !== "30d" || Boolean(query.kind) || Boolean(query.q.trim());
}

function dayWords(value: string): string {
    const date = new Date(`${value}T00:00:00`);
    return new Intl.DateTimeFormat("en-IE", { day: "numeric", month: "short" }).format(date);
}

/** The date chip: "Last 30 days", "Today", "3 Nov – 5 Nov". */
export function whenLabel(query: Pick<FollowUpsQuery, "when" | "start" | "end">): string {
    if (query.when === "custom" && query.start) {
        return query.end && query.end !== query.start
            ? `${dayWords(query.start)} – ${dayWords(query.end)}`
            : dayWords(query.start);
    }
    return WHEN_OPTIONS.find((option) => option.value === query.when)?.label ?? "Last 30 days";
}

/** For sentences: "today", "in the last 7 days", "on 3 Nov", "from 3 Nov to 5 Nov". */
export function whenPhrase(query: Pick<FollowUpsQuery, "when" | "start" | "end">): string {
    if (query.when === "custom" && query.start) {
        return query.end && query.end !== query.start
            ? `from ${dayWords(query.start)} to ${dayWords(query.end)}`
            : `on ${dayWords(query.start)}`;
    }
    if (query.when === "today") return "today";
    return query.when === "7d" ? "in the last 7 days" : "in the last 30 days";
}
