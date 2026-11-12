import { endOfDay, startOfDay, subDays } from "date-fns";

import type { WorkflowRunUsageResponse } from "@/client/types.gen";
import type { StatusTone } from "@/components/ui/status-pill";

/*
 * The Calls page's plain-English view of a stored call: who rang, what the
 * agent took down, how it ended. Everything here reads stored fields only:
 * the summary is the post-call review stored on the call, never made up here.
 */

type Context = Record<string, unknown> | null | undefined;

/**
 * The tabs over the list. Each is a filter the API can count. "Needs
 * follow-up" asks the API for the calls Follow-ups lists as still open (the
 * server reads them from the Follow-ups service itself), so the two agree.
 */
export type CallsTab = "all" | "follow_up" | "bookings" | "team";

export const CALLS_TABS: { value: CallsTab; label: string }[] = [
    { value: "all", label: "All" },
    { value: "follow_up", label: "Needs follow-up" },
    { value: "bookings", label: "Bookings" },
    { value: "team", label: "Passed to team" },
];

/**
 * Whether the date chip applies on a tab. "Needs follow-up" keeps
 * Follow-ups' own window (the last 30 days), or its count would differ.
 */
export function tabUsesDates(tab: CallsTab): boolean {
    return tab !== "follow_up";
}

/** The date chip's choices. "custom" carries its own start and end day. */
export type WhenPreset = "today" | "7d" | "30d" | "90d" | "all" | "custom";

export const WHEN_PRESETS: { value: Exclude<WhenPreset, "custom">; label: string }[] = [
    { value: "today", label: "Today" },
    { value: "7d", label: "Last 7 days" },
    { value: "30d", label: "Last 30 days" },
    { value: "90d", label: "Last 90 days" },
    { value: "all", label: "Any time" },
];

export const DEFAULT_WHEN: WhenPreset = "7d";

export type HandledBy = "agent" | "team";

export const HANDLED_BY_OPTIONS: { value: HandledBy; label: string }[] = [
    { value: "agent", label: "Your agent" },
    { value: "team", label: "Passed to your team" },
];

/** What the simple controls (tabs, search, chips, page) are set to. */
export interface CallsQuery {
    tab: CallsTab;
    q: string;
    when: WhenPreset;
    /** yyyy-mm-dd, only for when === "custom". */
    start: string | null;
    end: string | null;
    /** A stored outcome code, or null for any. */
    outcome: string | null;
    who: HandledBy | null;
    /** Only inbound calls that came in outside the agent's opening hours (set as times). */
    afterHours: boolean;
    page: number;
}

export const DEFAULT_QUERY: CallsQuery = {
    tab: "all",
    q: "",
    when: DEFAULT_WHEN,
    start: null,
    end: null,
    outcome: null,
    who: null,
    afterHours: false,
    page: 1,
};

/** Calls on one page of the list. */
export const PAGE_SIZE = 10;

const DAY = /^\d{4}-\d{2}-\d{2}$/;

function isTab(value: string | null): value is CallsTab {
    return CALLS_TABS.some((tab) => tab.value === value);
}

/** The simple controls as the URL has them; anything unreadable falls back to the default. */
export function callsQueryFromParams(params: URLSearchParams): CallsQuery {
    const tab = params.get("tab");
    const when = params.get("when");
    const start = params.get("start");
    const end = params.get("end");
    const who = params.get("who");
    const page = Number.parseInt(params.get("page") ?? "", 10);
    const custom = when === "custom" && start !== null && DAY.test(start) && (end === null || DAY.test(end));
    return {
        tab: isTab(tab) ? tab : "all",
        q: (params.get("q") ?? "").slice(0, 100),
        when: custom
            ? "custom"
            : WHEN_PRESETS.some((preset) => preset.value === when)
                ? (when as WhenPreset)
                : DEFAULT_WHEN,
        start: custom ? start : null,
        end: custom ? end : null,
        outcome: params.get("outcome") || null,
        who: who === "agent" || who === "team" ? who : null,
        afterHours: params.get("hours") === "after",
        page: Number.isFinite(page) && page > 1 ? page : 1,
    };
}

/**
 * The URL for a set of controls. Defaults are left out so a plain /usage is
 * the everyday view; `extra` carries the expert filters and the open call.
 */
export function callsQueryToParams(
    query: CallsQuery,
    extra: { filters?: string | null; call?: number | string | null } = {},
): URLSearchParams {
    const params = new URLSearchParams();
    if (query.tab !== "all") params.set("tab", query.tab);
    if (query.q.trim()) params.set("q", query.q.trim());
    if (query.when !== DEFAULT_WHEN) params.set("when", query.when);
    if (query.when === "custom" && query.start) {
        params.set("start", query.start);
        if (query.end) params.set("end", query.end);
    }
    if (query.outcome) params.set("outcome", query.outcome);
    if (query.who) params.set("who", query.who);
    if (query.afterHours) params.set("hours", "after");
    if (query.page > 1) params.set("page", String(query.page));
    if (extra.filters) params.set("filters", extra.filters);
    if (extra.call !== null && extra.call !== undefined && extra.call !== "") params.set("call", String(extra.call));
    return params;
}

function dayFromString(value: string): Date {
    const [year, month, day] = value.split("-").map(Number);
    return new Date(year, month - 1, day);
}

/** The local-time range the date chip stands for, or null for any time. */
export function dateRangeFor(query: Pick<CallsQuery, "when" | "start" | "end">, now: Date): { from: Date; to: Date } | null {
    switch (query.when) {
        case "today":
            return { from: startOfDay(now), to: endOfDay(now) };
        case "7d":
            return { from: startOfDay(subDays(now, 6)), to: endOfDay(now) };
        case "30d":
            return { from: startOfDay(subDays(now, 29)), to: endOfDay(now) };
        case "90d":
            return { from: startOfDay(subDays(now, 89)), to: endOfDay(now) };
        case "custom": {
            if (!query.start) return null;
            const from = startOfDay(dayFromString(query.start));
            const to = endOfDay(dayFromString(query.end ?? query.start));
            return from <= to ? { from, to } : { from: startOfDay(to), to: endOfDay(from) };
        }
        default:
            return null;
    }
}

/** The date chip's label: a preset's name, or the days chosen. */
export function whenLabel(query: Pick<CallsQuery, "when" | "start" | "end">): string {
    if (query.when === "custom" && query.start) {
        const format = (value: string) =>
            dayFromString(value).toLocaleDateString("en-IE", { day: "numeric", month: "short" });
        return !query.end || query.end === query.start
            ? format(query.start)
            : `${format(query.start)} – ${format(query.end)}`;
    }
    return WHEN_PRESETS.find((preset) => preset.value === query.when)?.label ?? "Last 7 days";
}

/** The date chip in a sentence: "in the last 7 days", "today", "between 1 Nov and 3 Nov". */
export function whenPhrase(query: Pick<CallsQuery, "when" | "start" | "end">): string {
    switch (query.when) {
        case "today":
            return "today";
        case "all":
            return "at any time";
        case "custom": {
            const label = whenLabel(query);
            return label.includes("–") ? `between ${label.replace(" – ", " and ")}` : `on ${label}`;
        }
        default:
            return `in the ${whenLabel(query).toLowerCase()}`;
    }
}

/** A row of the Calls list, as the usage API returns it. */
export type CallRow = WorkflowRunUsageResponse;

/** One filter object as the usage API takes it (see FILTERS_DESCRIPTION). */
export interface ApiFilter {
    attribute: string;
    type: string;
    value: unknown;
}

/** The filter a tab adds, or null for All. */
export function tabFilter(tab: CallsTab): ApiFilter | null {
    switch (tab) {
        case "bookings":
            // The calls the calendar confirmed a booking on, as Home and
            // Reports count "Bookings taken"; the server fills in the calls.
            return { attribute: "bookingMade", type: "runIds", value: {} };
        case "team":
            return { attribute: "handledBy", type: "radio", value: { status: "team" } };
        case "follow_up":
            // The server fills in the open follow-ups; nothing is sent.
            return { attribute: "needsFollowUp", type: "runIds", value: {} };
        default:
            return null;
    }
}

/**
 * The search box, outcome chip, "Who handled it" and "Outside opening hours"
 * chips as API filters (no tab, no dates). The server fills in the agents'
 * opening hours for the last one, as Home counts them.
 */
export function chipFilters(query: Pick<CallsQuery, "q" | "outcome" | "who"> & { afterHours?: boolean }): ApiFilter[] {
    const filters: ApiFilter[] = [];
    const q = query.q.trim();
    if (q) filters.push({ attribute: "callerSearch", type: "text", value: { value: q } });
    if (query.outcome) {
        filters.push({ attribute: "dispositionCode", type: "multiSelect", value: { codes: [query.outcome] } });
    }
    if (query.who) filters.push({ attribute: "handledBy", type: "radio", value: { status: query.who } });
    if (query.afterHours) filters.push({ attribute: "afterHours", type: "openingHours", value: {} });
    return filters;
}

/** True when anything narrows the list beyond the everyday view (the date chip's default included). */
export function isNarrowed(query: CallsQuery, expertFilterCount: number): boolean {
    return (
        query.when !== "all" ||
        Boolean(query.q.trim()) ||
        Boolean(query.outcome) ||
        Boolean(query.who) ||
        query.afterHours ||
        expertFilterCount > 0
    );
}

/* ---------- One call, in plain words ---------- */

function text(value: unknown): string | null {
    if (typeof value === "string") return value.trim() || null;
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
    return null;
}

/** What the agent captured on the call: `extracted_variables`, else the top-level copies. */
export function capturedValues(gathered: Context): Record<string, unknown> {
    const extracted = gathered?.extracted_variables;
    if (extracted && typeof extracted === "object" && !Array.isArray(extracted)) {
        return extracted as Record<string, unknown>;
    }
    const values: Record<string, unknown> = {};
    for (const key of Object.keys(DETAIL_LABELS)) {
        if (gathered && key in gathered) values[key] = gathered[key];
    }
    return values;
}

/** The caller's name, if the agent took it down. */
export function callerNameOf(gathered: Context): string | null {
    return text(capturedValues(gathered).caller_name) ?? text(gathered?.caller_name);
}

/** The number shown for a call: the caller's on inbound calls, the number called otherwise. */
export function callNumberOf(run: {
    call_type?: string | null;
    caller_number?: string | null;
    called_number?: string | null;
}): string | null {
    return (run.call_type === "inbound" ? run.caller_number : run.called_number) || null;
}

/** A number that can be rung: carriers send "anonymous" or "restricted" for a withheld one. */
export function isDialable(number: string | null | undefined): number is string {
    return typeof number === "string" && (number.match(/\d/g)?.length ?? 0) >= 6;
}

/** "+353871234567" → "+353 87 123 4567"; anything else as stored. */
export function formatPhone(number: string): string {
    const irish = /^\+353(\d{2})(\d{3})(\d{3,4})$/.exec(number);
    if (irish) return `+353 ${irish[1]} ${irish[2]} ${irish[3]}`;
    return number;
}

/** The plain labels for the details the starter templates capture. */
export const DETAIL_LABELS: Record<string, string> = {
    caller_name: "Name",
    callback_number: "Number to call back",
    call_reason: "Reason for calling",
    booking_outcome: "Booking",
    booking_date: "Date",
    booking_time: "Time",
    party_size: "Party size",
    special_requests: "Special requests",
    appointment_type: "Appointment",
    patient_status: "New or existing patient",
    service: "Service",
    stylist: "Stylist",
    urgency: "How urgent",
    job_address: "Address",
    property: "Property",
    satisfaction_score: "Satisfaction score",
};

const BOOKING_WORDS: Record<string, string> = {
    booked: "Booked",
    moved: "Moved to a new time",
    requested: "Asked for (your team to confirm)",
    cancelled: "Cancelled",
};

/** "do_not_call" → "Do not call". */
function sentence(key: string): string {
    const words = key.replace(/[_-]+/g, " ").trim().toLowerCase();
    return words.charAt(0).toUpperCase() + words.slice(1);
}

/** "2026-11-14" → "Sat 14 Nov"; anything else as stored. */
export function formatBookingDate(value: string): string {
    if (!DAY.test(value)) return value;
    const date = dayFromString(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleDateString("en-IE", { weekday: "short", day: "numeric", month: "short" }).replace(",", "");
}

function clock(hours: number, minutes: number): string {
    const period = hours < 12 ? "am" : "pm";
    const hour = hours % 12 === 0 ? 12 : hours % 12;
    return `${hour}:${String(minutes).padStart(2, "0")} ${period}`;
}

/** "19:30" → "7:30 pm"; anything else as stored. */
export function formatBookingTime(value: string): string {
    const match = /^(\d{1,2}):(\d{2})$/.exec(value);
    if (!match) return value;
    const hours = Number(match[1]);
    const minutes = Number(match[2]);
    if (hours > 23 || minutes > 59) return value;
    return clock(hours, minutes);
}

export interface CallDetail {
    key: string;
    label: string;
    value: string;
}

/**
 * The details the agent took, labelled plainly, in the template's order.
 * Empty values, nested data and tag_* helpers are left out.
 */
export function callDetails(gathered: Context): CallDetail[] {
    const values = capturedValues(gathered);
    const known = Object.keys(DETAIL_LABELS);
    const keys = [
        ...known.filter((key) => key in values),
        ...Object.keys(values).filter((key) => !known.includes(key) && !key.startsWith("tag_")),
    ];
    const details: CallDetail[] = [];
    for (const key of keys) {
        const raw = values[key];
        let value = typeof raw === "boolean" ? (raw ? "Yes" : "No") : text(raw);
        if (!value) continue;
        if (key === "booking_outcome") value = BOOKING_WORDS[value.toLowerCase()] ?? sentence(value);
        if (key === "booking_date") value = formatBookingDate(value);
        if (key === "booking_time") value = formatBookingTime(value);
        if (key === "callback_number") value = formatPhone(value);
        details.push({ key, label: DETAIL_LABELS[key] ?? sentence(key), value });
    }
    return details;
}

/**
 * A short line on what the call was about, from what the agent captured: the
 * reason for calling, else the booking it took down. Null when it took down
 * neither (no summary is ever made up).
 */
export function whatHappened(gathered: Context): string | null {
    const values = capturedValues(gathered);
    const reason = text(values.call_reason);
    if (reason) return reason;
    const booking = text(values.booking_outcome)?.toLowerCase();
    if (!booking || !(booking in BOOKING_WORDS)) return null;
    const lead: Record<string, string> = {
        booked: "Booking made",
        moved: "Booking moved",
        requested: "Booking asked for",
        cancelled: "Booking cancelled",
    };
    const date = text(values.booking_date);
    const time = text(values.booking_time);
    const size = text(values.party_size);
    const when = [date && formatBookingDate(date), time && formatBookingTime(time)].filter(Boolean).join(", ");
    return [lead[booking], when, size && `${size} ${size === "1" ? "person" : "people"}`]
        .filter(Boolean)
        .join(" · ");
}

/**
 * "What happened" for a row: the stored post-call summary when the call has
 * one, else what the agent captured (reason or booking line).
 */
export function callSummary(run: { summary?: string | null; gathered_context?: Context }): string | null {
    return text(run.summary) ?? whatHappened(run.gathered_context);
}

/** A call not marked finished this long after it started never will be (Home uses the same hour). */
export const IN_PROGRESS_FOR_MS = 60 * 60 * 1000;

/** Whether a call is still going on: not marked finished, and started within the hour. */
export function isInProgress(
    run: { is_completed?: boolean | null; created_at: string },
    now: number = Date.now(),
): boolean {
    if (run.is_completed !== false) return false;
    const started = new Date(run.created_at).getTime();
    return Number.isFinite(started) && now - started < IN_PROGRESS_FOR_MS;
}

/**
 * ``value`` split around each case-insensitive occurrence of ``query``, so
 * the matches can be marked. A blank query gives the text unmarked.
 */
export function highlightParts(value: string, query: string): { text: string; hit: boolean }[] {
    const needle = query.trim();
    if (!needle) return [{ text: value, hit: false }];
    const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const parts: { text: string; hit: boolean }[] = [];
    let last = 0;
    for (const match of value.matchAll(new RegExp(escaped, "gi"))) {
        const at = match.index ?? 0;
        if (at > last) parts.push({ text: value.slice(last, at), hit: false });
        parts.push({ text: match[0], hit: true });
        last = at + match[0].length;
    }
    if (last < value.length) parts.push({ text: value.slice(last), hit: false });
    return parts.length > 0 ? parts : [{ text: value, hit: false }];
}

const TRANSFERRED_STATUSES = new Set(["transfer_call", "call_transferred"]);

/** Whether the call was handed to a person (the rule Reports and the "Passed to team" tab use). */
export function isPassedToTeam(gathered: Context): boolean {
    return (
        TRANSFERRED_STATUSES.has(String(gathered?.call_status ?? "")) ||
        gathered?.mapped_call_disposition === "XFER"
    );
}

/** A "Lines were busy" call someone on the team picked up when it was forwarded. */
export function linesBusyAnswered(gathered: Context): boolean {
    const forward = gathered?.lines_busy_forward;
    return Boolean(forward && typeof forward === "object" && (forward as Record<string, unknown>).result === "answered");
}

/** Plain words for the outcome codes the app writes itself. */
const OUTCOME_WORDS: Record<string, string> = {
    transfer_call: "Passed to your team",
    call_transferred: "Passed to your team",
    user_hangup: "Caller hung up",
    end_call: "Call finished",
    voicemail_detected: "Voicemail",
    do_not_call: "Asked not to be called",
    "no-answer": "No answer",
    busy: "Line busy",
    failed: "Didn't connect",
    canceled: "Didn't connect",
    error: "Didn't connect",
    pipeline_error: "Call dropped",
    unexpected_error: "Call dropped",
    lines_busy: "Lines were busy",
};

/**
 * A readable outcome: "callback_requested" → "Callback requested". Short
 * all-capital codes a business chose itself ("XFER") are left as they are.
 */
export function outcomeLabel(code: string): string {
    if (code in OUTCOME_WORDS) return OUTCOME_WORDS[code];
    if (/^[A-Z0-9_]+$/.test(code) && code.length <= 6) return code;
    return sentence(code);
}

const OUTCOME_TONES: Record<string, StatusTone> = {
    qualified: "ok",
    booking_made: "ok",
    time_was_full: "warn",
    transfer_not_answered: "bad",
    callback_requested: "warn",
    do_not_call: "bad",
    failed: "bad",
    canceled: "bad",
    error: "bad",
    busy: "bad",
    "no-answer": "bad",
    pipeline_error: "bad",
    unexpected_error: "bad",
    lines_busy: "warn",
};

/** The outcome chip for a call: its stored outcome in plain words. */
export function callOutcome(
    run: {
        disposition?: string | null;
        gathered_context?: Context;
        is_completed?: boolean | null;
        created_at?: string;
    },
    now: number = Date.now(),
): { label: string; tone: StatusTone } {
    if (run.created_at && isInProgress({ is_completed: run.is_completed, created_at: run.created_at }, now)) {
        return { label: "In progress", tone: "live" };
    }
    const gathered = run.gathered_context;
    if (isPassedToTeam(gathered)) return { label: "Passed to your team", tone: "info" };
    const code = run.disposition ?? text(gathered?.mapped_call_disposition);
    // Every line was busy: Home's rule, put through to the team when someone picked up.
    if (code === "lines_busy" && linesBusyAnswered(gathered)) {
        return { label: "Lines were busy · passed to your team", tone: "info" };
    }
    const tags = gathered?.call_tags;
    // The engine tags a call where the caller spoke; a hang-up without that tag never got going.
    if (code === "user_hangup" && Array.isArray(tags) && !tags.includes("user_speech") && tags.length > 0) {
        return { label: "Hung up without speaking", tone: "mute" };
    }
    if (!code) return { label: "Not recorded", tone: "mute" };
    return { label: outcomeLabel(code), tone: OUTCOME_TONES[code] ?? "mute" };
}

/* ---------- Times and lengths ---------- */

/** "3m 5s", "45s", "2m". */
export function formatDuration(seconds: number): string {
    const minutes = Math.floor(seconds / 60);
    const rest = Math.round(seconds % 60);
    if (minutes === 0) return `${rest}s`;
    if (rest === 0) return `${minutes}m`;
    return `${minutes}m ${rest}s`;
}

/** "2:12": a call's length as the list shows it. */
export function formatLength(seconds: number): string {
    const whole = Math.max(0, Math.round(seconds));
    return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/** "2 min 12 s", "45 s": a call's length in the call panel. */
export function formatLengthWords(seconds: number): string {
    const whole = Math.max(0, Math.round(seconds));
    const minutes = Math.floor(whole / 60);
    const rest = whole % 60;
    if (minutes === 0) return `${rest} s`;
    return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} s`;
}

/** "2 minutes 12 seconds", for screen readers. */
export function spokenLength(seconds: number): string {
    const whole = Math.max(0, Math.round(seconds));
    const minutes = Math.floor(whole / 60);
    const rest = whole % 60;
    const parts = [];
    if (minutes) parts.push(`${minutes} ${minutes === 1 ? "minute" : "minutes"}`);
    if (rest || !minutes) parts.push(`${rest} ${rest === 1 ? "second" : "seconds"}`);
    return parts.join(" ");
}

interface ZonedParts {
    year: number;
    month: number;
    day: number;
    hour: number;
    minute: number;
}

function zonedParts(date: Date, timezone?: string | null): ZonedParts {
    const options: Intl.DateTimeFormatOptions = {
        year: "numeric",
        month: "numeric",
        day: "numeric",
        hour: "numeric",
        minute: "numeric",
        hourCycle: "h23",
    };
    let parts: Intl.DateTimeFormatPart[];
    try {
        parts = new Intl.DateTimeFormat("en-GB", { ...options, timeZone: timezone || undefined }).formatToParts(date);
    } catch {
        // An unknown zone name: the browser's own zone is better than nothing.
        parts = new Intl.DateTimeFormat("en-GB", options).formatToParts(date);
    }
    const get = (type: string) => Number(parts.find((part) => part.type === type)?.value ?? 0);
    return { year: get("year"), month: get("month"), day: get("day"), hour: get("hour") % 24, minute: get("minute") };
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * When a call was, as an owner says it, in the workspace's time zone:
 * "Today 1:41 pm", "Yesterday 9:12 pm", "Mon 2 Nov, 9:12 pm", and the year
 * once it isn't this one ("3 Nov 2025, 9:12 pm").
 */
export function formatCallWhen(value: string, timezone?: string | null, now: Date = new Date()): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    const call = zonedParts(date, timezone);
    const today = zonedParts(now, timezone);
    const time = clock(call.hour, call.minute);
    const callDay = Date.UTC(call.year, call.month - 1, call.day);
    const daysAgo = Math.round((Date.UTC(today.year, today.month - 1, today.day) - callDay) / 86_400_000);
    if (daysAgo === 0) return `Today ${time}`;
    if (daysAgo === 1) return `Yesterday ${time}`;
    const weekday = WEEKDAYS[new Date(callDay).getUTCDay()];
    const dayMonth = `${call.day} ${MONTHS[call.month - 1]}`;
    if (call.year === today.year) return `${weekday} ${dayMonth}, ${time}`;
    return `${dayMonth} ${call.year}, ${time}`;
}

/**
 * "Fri 6 Nov 2026, 13:12" in the workspace's time zone: Irish/UK order and a
 * 24-hour clock, for the full call page's technical record.
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

/** The pager's page numbers with gaps: [1, 2, 3, "…", 32]. */
export function pageList(current: number, total: number): (number | "gap")[] {
    if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
    const pages = new Set([1, total, current - 1, current, current + 1]);
    if (current <= 3) [2, 3, 4].forEach((page) => pages.add(page));
    if (current >= total - 2) [total - 3, total - 2, total - 1].forEach((page) => pages.add(page));
    const sorted = [...pages].filter((page) => page >= 1 && page <= total).sort((a, b) => a - b);
    const list: (number | "gap")[] = [];
    sorted.forEach((page, index) => {
        if (index > 0 && page - sorted[index - 1] > 1) list.push("gap");
        list.push(page);
    });
    return list;
}
