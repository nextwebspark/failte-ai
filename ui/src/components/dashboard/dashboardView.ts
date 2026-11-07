/**
 * Words and formats for Home and Follow-ups. Pure, so they're easy to test.
 * Every number comes from the dashboard API; nothing here invents one.
 */
import { formatDuration, formatPhone } from "@/app/usage/callsView";
import type {
    CallResult,
    DashboardRange,
    FollowUpItem,
    FollowUpKind,
    NotAnsweringReason,
} from "@/client/types.gen";

/** The chip colours the design uses: brand, sky, amber, danger, neutral. */
export type ChipTone = "brand" | "sky" | "amber" | "danger" | "neutral";

export const CHIP_CLASSES: Record<ChipTone, string> = {
    brand: "bg-brand-dim text-brand",
    sky: "bg-sky-dim text-sky",
    amber: "bg-amber-dim text-amber",
    danger: "bg-danger-dim text-danger",
    neutral: "bg-panel-2 text-ink-2",
};

/** The coloured rule on the left of a follow-up. */
export const RULE_CLASSES: Record<ChipTone, string> = {
    brand: "bg-brand",
    sky: "bg-sky",
    amber: "bg-amber",
    danger: "bg-danger",
    neutral: "bg-line",
};

export const RESULT_WORDS: Record<CallResult, { label: string; tone: ChipTone }> = {
    handled: { label: "Handled by your agent", tone: "brand" },
    booking_made: { label: "Booking made", tone: "brand" },
    passed_to_team: { label: "Passed to your team", tone: "sky" },
    transfer_not_answered: { label: "Transfer not answered", tone: "danger" },
    callback_requested: { label: "Callback requested", tone: "amber" },
    hung_up_silent: { label: "Hung up without speaking", tone: "neutral" },
    hung_up_early: { label: "Hung up early", tone: "neutral" },
    not_connected: { label: "Didn't connect", tone: "neutral" },
    call_dropped: { label: "Call dropped", tone: "danger" },
    in_progress: { label: "On the line now", tone: "sky" },
};

export const FOLLOW_UP_WORDS: Record<FollowUpKind, { chip: string; filter: string; tone: ChipTone }> = {
    callback: { chip: "Callback requested", filter: "Call back", tone: "amber" },
    transfer_not_answered: { chip: "Transfer not answered", filter: "Transfer not answered", tone: "danger" },
    repeat_caller: { chip: "Rang more than once", filter: "Rang more than once", tone: "sky" },
    unanswered_question: { chip: "Add an answer", filter: "Couldn't answer", tone: "sky" },
    time_was_full: { chip: "Time was full", filter: "Time was full", tone: "amber" },
};

export const FOLLOW_UP_KINDS: FollowUpKind[] = [
    "callback",
    "transfer_not_answered",
    "repeat_caller",
    "unanswered_question",
    "time_was_full",
];

/** One follow-up's key: a call can have one per kind. */
export function followUpKey(item: Pick<FollowUpItem, "run_id" | "kind">): string {
    return `${item.run_id}-${item.kind}`;
}

/** The kinds the call review raises; each is marked done on its own (?kind=). */
export function markKind(kind: FollowUpKind): FollowUpKind | null {
    return kind === "unanswered_question" || kind === "time_was_full" ? kind : null;
}

export const RANGE_OPTIONS: { value: DashboardRange; label: string }[] = [
    { value: "today", label: "Today" },
    { value: "7d", label: "7 days" },
    { value: "30d", label: "30 days" },
];

function safeZone(timezone?: string | null): string | undefined {
    if (!timezone) return undefined;
    try {
        new Intl.DateTimeFormat("en-IE", { timeZone: timezone });
        return timezone;
    } catch {
        return undefined;
    }
}

function parts(date: Date, timezone: string | null | undefined, options: Intl.DateTimeFormatOptions) {
    return new Intl.DateTimeFormat("en-IE", { ...options, timeZone: safeZone(timezone) }).formatToParts(date);
}

function part(list: Intl.DateTimeFormatPart[], type: Intl.DateTimeFormatPartTypes): string {
    return list.find((p) => p.type === type)?.value ?? "";
}

/** "Thursday 5 November" in the business's zone. */
export function dayLine(date: Date, timezone?: string | null): string {
    const p = parts(date, timezone, { weekday: "long", day: "numeric", month: "long" });
    return `${part(p, "weekday")} ${part(p, "day")} ${part(p, "month")}`;
}

/** "1:41 pm", the same clock the Calls page uses. */
export function clockTime(value: string | Date, timezone?: string | null): string {
    const date = typeof value === "string" ? new Date(value) : value;
    if (Number.isNaN(date.getTime())) return "";
    const p = parts(date, timezone, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
    const hours = Number(part(p, "hour")) % 24;
    const hour = hours % 12 === 0 ? 12 : hours % 12;
    return `${hour}:${part(p, "minute")} ${hours < 12 ? "am" : "pm"}`;
}

function dayKey(date: Date, timezone?: string | null): string {
    const p = parts(date, timezone, { year: "numeric", month: "2-digit", day: "2-digit" });
    return `${part(p, "year")}-${part(p, "month")}-${part(p, "day")}`;
}

/** "1:41 pm" today, "Yesterday 1:41 pm", else "Thu 5 Nov, 1:41 pm". */
export function callWhen(value: string, timezone: string | null | undefined, now: Date = new Date()): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const clock = clockTime(date, timezone);
    if (dayKey(date, timezone) === dayKey(now, timezone)) return clock;
    const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
    if (dayKey(date, timezone) === dayKey(yesterday, timezone)) return `Yesterday ${clock}`;
    const p = parts(date, timezone, { weekday: "short", day: "numeric", month: "short" });
    return `${part(p, "weekday")} ${part(p, "day")} ${part(p, "month")}, ${clock}`;
}

/** "2 h 30 min", "45 min", "3 days": how long something has waited. */
export function waitWords(minutes: number): string {
    const whole = Math.max(0, Math.round(minutes));
    if (whole < 60) return `${whole} min`;
    const hours = Math.floor(whole / 60);
    if (hours >= 48) return `${Math.floor(hours / 24)} days`;
    const rest = whole % 60;
    return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

export function minutesSince(value: string, now: Date = new Date()): number {
    return (now.getTime() - new Date(value).getTime()) / 60000;
}

/** "1m 48s", via the Calls page's own formatter; null for no length. */
export function callLength(seconds: number | null | undefined): string | null {
    if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return null;
    return formatDuration(seconds);
}

/** A dialler link: digits and a leading +. */
export function telHref(number: string): string {
    return `tel:${number.replace(/[^\d+]/g, "")}`;
}

/** "Here's how your phone agent did today, Thursday 5 November." */
/**
 * Home's after-hours line: "3 calls came in outside opening hours", and which
 * agents aren't counted because their hours aren't set as times.
 */
export function afterHoursWords(afterHours: {
    calls: number | null;
    agents_without_hours: { id: number; name: string }[];
}): { count: string | null; note: string | null } {
    const missing = afterHours.agents_without_hours.map((a) => a.name);
    const count =
        afterHours.calls === null
            ? null
            : `${afterHours.calls === 1 ? "1 call" : `${afterHours.calls} calls`} came in outside opening hours`;
    let note: string | null = null;
    if (afterHours.calls === null) {
        if (missing.length) note = "Set your opening hours as times to see how many calls come in when you're closed.";
    } else if (missing.length) {
        const names = missing.length <= 2 ? missing.join(" and ") : `${missing.length} agents`;
        note = `Not counted: ${names}, with no opening hours set as times.`;
    }
    return { count, note };
}

export function rangeSentence(range: DashboardRange, now: Date, timezone?: string | null): string {
    if (range === "today") return `Here's how your phone agent did today, ${dayLine(now, timezone)}.`;
    return `Here's how your phone agent did in the last ${range === "7d" ? "7" : "30"} days.`;
}

/** The Calls tile's label for the range. */
export function callsTileLabel(range: DashboardRange): string {
    return range === "today" ? "Calls today" : "Calls";
}

/** "+8 on last Thursday", "Same as the 7 days before"; null when hidden. */
export function changeWords(
    range: DashboardRange,
    change: number | null | undefined,
    now: Date,
    timezone?: string | null,
): { sign: "up" | "down" | "same"; amount: string; rest: string } | null {
    if (change == null) return null;
    const compared =
        range === "today"
            ? `last ${parts(now, timezone, { weekday: "long" }).find((p) => p.type === "weekday")?.value ?? ""}`
            : `the ${range === "7d" ? "7" : "30"} days before`;
    if (change === 0) return { sign: "same", amount: "", rest: `Same as ${compared}` };
    return {
        sign: change > 0 ? "up" : "down",
        amount: change > 0 ? `+${change}` : `−${Math.abs(change)}`,
        rest: ` on ${compared}`,
    };
}

/** What the "not answering" banner says, and the fix it offers. */
export function notAnsweringWords(reason: NotAnsweringReason): {
    title: string;
    detail: string;
    fix: { label: string; href: string; requires: "billing:read" | "telephony:read" | "agents:write" | "agents:read" };
} {
    switch (reason) {
        case "no_credit":
            return {
                title: "Your agent isn't answering",
                detail: "Your credit has run out, so calls can't start. Top up to switch it back on.",
                fix: { label: "Top up credit", href: "/billing", requires: "billing:read" },
            };
        case "number_off":
            return {
                title: "Your agent isn't answering",
                detail: "Your phone number is switched off, so calls don't reach your agent.",
                fix: { label: "Check your number", href: "/telephony-configurations", requires: "telephony:read" },
            };
        case "agent_off":
            return {
                title: "Your agent isn't answering",
                detail: "Your agent is switched off, so nobody answers calls to your number.",
                fix: { label: "Open your agents", href: "/workflow", requires: "agents:read" },
            };
        case "no_agent":
            return {
                title: "You don't have a phone agent yet",
                detail: "Set one up and it starts answering your calls.",
                fix: { label: "Create your agent", href: "/workflow/create", requires: "agents:write" },
            };
        case "no_number":
        default:
            return {
                title: "Your agent isn't answering",
                detail: "No phone number is linked to your agent yet, so it can't take calls.",
                fix: { label: "Link a number", href: "/telephony-configurations", requires: "telephony:read" },
            };
    }
}

/** "Last call 2 h ago", "Last call 3 days ago", "No calls yet". */
export function lastCallWords(value: string | null | undefined, now: Date = new Date()): string {
    if (!value) return "No calls yet";
    const minutes = minutesSince(value, now);
    if (minutes < 1) return "Last call just now";
    return `Last call ${waitWords(minutes)} ago`;
}

/** Who the caller is: their name if the agent took it, else their number. */
export function callerWords(item: { caller_name?: string | null; caller_number?: string | null }): string {
    return item.caller_name || (item.caller_number ? formatPhone(item.caller_number) : "Unknown caller");
}

/** The number to ring back: the one they asked for, else the one they rang from. */
export function callBackNumber(item: Pick<FollowUpItem, "callback_number" | "caller_number">): string | null {
    return item.callback_number || item.caller_number || null;
}

export function followUpTitle(item: FollowUpItem): string {
    switch (item.kind) {
        case "callback":
            return `Call back ${callerWords(item)}`;
        case "transfer_not_answered":
            return "Transfer not answered";
        case "unanswered_question":
            return "Your agent couldn't answer";
        case "time_was_full":
            return "Time was full";
        case "repeat_caller":
        default:
            return `${callerWords(item)} rang ${item.repeat_count ?? 2} times`;
    }
}

/** The detail line: what the caller said they wanted, when the agent wrote it down. */
export function followUpDetail(item: FollowUpItem, timezone?: string | null, now: Date = new Date()): string {
    const repeat =
        item.repeat_count && item.repeat_count > 1 && item.first_call_at
            ? `Rang ${item.repeat_count} times since ${callWhen(item.first_call_at, timezone, now)} and didn't reach anyone.`
            : null;
    switch (item.kind) {
        case "callback":
            return item.call_reason ?? "Asked for someone to call them back.";
        case "transfer_not_answered": {
            const base = item.call_reason
                ? item.call_reason
                : "Your agent tried to pass the call to your team, but nobody picked up.";
            return repeat ? `${base} ${repeat}` : base;
        }
        case "unanswered_question": {
            const questions = item.questions ?? [];
            return questions.length
                ? `${questions.map((q) => `“${q}”`).join(" ")} Add the answer once and your agent uses it on every call.`
                : "The caller asked something your agent didn't know.";
        }
        case "time_was_full":
            return item.summary ?? "The caller wanted a time that was full.";
        case "repeat_caller":
        default:
            return repeat ?? "Rang more than once and didn't reach anyone.";
    }
}

/** Calls-per-hour bars to draw: from 08:00 to 20:00, widened to any hour with calls. */
export function hourWindow(hours: number[]): { start: number; end: number } {
    const busy = hours.map((n, h) => (n > 0 ? h : -1)).filter((h) => h >= 0);
    const start = Math.min(8, ...(busy.length ? [busy[0]] : []));
    const end = Math.max(20, ...(busy.length ? [busy[busy.length - 1]] : []));
    return { start, end };
}

/**
 * The hour worth labelling: the busiest, only when it clearly stands out
 * (at least 3 calls and half again the average busy hour). Ties pick none.
 */
export function busiestHour(hours: number[]): number | null {
    const max = Math.max(0, ...hours);
    if (max < 3) return null;
    const busy = hours.filter((n) => n > 0);
    const mean = busy.reduce((a, b) => a + b, 0) / busy.length;
    if (max < mean * 1.5) return null;
    const at = hours.filter((n) => n === max);
    return at.length === 1 ? hours.indexOf(max) : null;
}

/** "09:00" for an hour of the day. */
export function hourLabel(hour: number): string {
    return `${String(hour).padStart(2, "0")}:00`;
}

/** "€14.20". */
export function euros(value: string | number): string {
    const amount = typeof value === "string" ? Number(value) : value;
    return new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR" }).format(amount);
}

/** The agent's answers with one more: "Q: … A: …" on a line of its own. */
export function appendAnswer(existing: string, question: string, answer: string): string {
    const line = `Q: ${question.trim().replace(/\s+/g, " ")} A: ${answer.trim().replace(/\s+/g, " ")}`;
    const before = existing.trimEnd();
    return before ? `${before}\n${line}` : line;
}

/**
 * Home's "today in one line": the range's headline counts as short phrases,
 * e.g. 6 calls · 4 handled by your agent · 3 bookings taken · 1 asked for a
 * call back. Only counts the API returned; a phrase whose count is 0 is left
 * out (except the calls and handled counts). Empty when there were no calls.
 */
export function todayLine(
    tiles: {
        calls: number;
        handled: number;
        passed_to_team: number;
        callbacks_requested: number;
        bookings_taken: number;
    },
    bookingsLabel: string | null | undefined,
): { value: number; words: string }[] {
    if (tiles.calls <= 0) return [];
    const parts: { value: number; words: string }[] = [
        { value: tiles.calls, words: tiles.calls === 1 ? "call" : "calls" },
        { value: tiles.handled, words: "handled by your agent" },
    ];
    if (bookingsLabel && tiles.bookings_taken > 0) parts.push({ value: tiles.bookings_taken, words: bookingsLabel });
    if (tiles.passed_to_team > 0) parts.push({ value: tiles.passed_to_team, words: "passed to your team" });
    if (tiles.callbacks_requested > 0) {
        parts.push({ value: tiles.callbacks_requested, words: "asked for a call back" });
    }
    return parts;
}

/** "09:00–10:00" for an hour of the day. */
export function hourSpan(hour: number): string {
    return `${hourLabel(hour)}–${hourLabel((hour + 1) % 24)}`;
}
