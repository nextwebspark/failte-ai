/**
 * Opening hours as times (`OpeningHours` on the API): per weekday, Monday
 * first, closed or one or more open ranges in the business's time zone. A
 * range whose closing time is at or before its opening time runs past
 * midnight; 00:00–00:00 is open all day. Mirrors
 * `api/schemas/opening_hours.py` and `api/services/workflow/opening_hours.py`.
 */

import type { OpeningHours, OpenRange } from "@/client/types.gen";
import { browserTimeZone } from "@/lib/appointmentHours";

export type { OpeningHours, OpenRange };

export const MAX_RANGES_PER_DAY = 4;
export const MAX_NOTE_LENGTH = 200;
const DAY = 24 * 60;
const CLOCK = /^([01]\d|2[0-3]):([0-5]\d)$/;

export const DAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;
export const DAY_LONG = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"] as const;

/** Every quarter hour, "00:00" to "23:45", for the time pickers. */
export const TIME_OPTIONS: string[] = Array.from({ length: 96 }, (_, i) => clock(i * 15));

function clock(minutes: number): string {
    const m = ((minutes % DAY) + DAY) % DAY;
    return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

function minutes(value: string): number {
    const [h, m] = value.split(":").map(Number);
    return h * 60 + m;
}

/** Minutes from the opening day's midnight: [start, end), end past 1440 overnight. */
function span(range: OpenRange): [number, number] {
    const start = minutes(range.open);
    const close = minutes(range.close);
    return [start, close > start ? close : close + DAY];
}

/** The days of a schedule, always seven lists (Monday first). */
export function weekOf(hours: OpeningHours): OpenRange[][] {
    return Array.from({ length: 7 }, (_, i) => [...((hours.days as OpenRange[][] | undefined)?.[i] ?? [])]);
}

/** Monday to Friday 9 to 5, closed at the weekend, in this browser's zone. */
export function defaultOpeningHours(): OpeningHours {
    const nineToFive = [{ open: "09:00", close: "17:00" }];
    return {
        days: [nineToFive, nineToFive, nineToFive, nineToFive, nineToFive, [], []],
        timezone: browserTimeZone(),
        transfer_only_when_open: true,
        note: null,
    } as OpeningHours;
}

function parts(m: number): { number: string; suffix: "am" | "pm" } {
    const v = ((m % DAY) + DAY) % DAY;
    const hour = Math.floor(v / 60);
    const minute = v % 60;
    const h12 = hour % 12 || 12;
    return { number: minute ? `${h12}:${String(minute).padStart(2, "0")}` : String(h12), suffix: hour < 12 ? "am" : "pm" };
}

function spoken(m: number): string {
    if (m % DAY === 0) return "midnight";
    const p = parts(m);
    return `${p.number} ${p.suffix}`;
}

/** As the agent says one range: "12 to 3 pm", "11 am to 3 pm", "6 pm to 2 am". */
function spokenRange(range: OpenRange): string {
    const [start, end] = span(range);
    if (start === 0 && end === DAY) return "open 24 hours";
    if (start !== 0 && end < DAY) {
        const a = parts(start);
        const b = parts(end);
        if (a.suffix === b.suffix) return `${a.number} to ${b.number} ${b.suffix}`;
    }
    return `${spoken(start)} to ${spoken(end)}`;
}

/** As a day chip shows one range: "12–3 pm", "8:30 am–6 pm", "6 pm–2 am". */
export function rangeLabel(range: OpenRange): string {
    const [start, end] = span(range);
    if (start === 0 && end === DAY) return "Open 24h";
    if (start !== 0 && end < DAY) {
        const a = parts(start);
        const b = parts(end);
        if (a.suffix === b.suffix) return `${a.number}–${b.number} ${b.suffix}`;
    }
    return `${spoken(start)}–${spoken(end)}`;
}

/** "17:30" → "5:30 pm" for the time pickers. */
export function timeLabel(value: string): string {
    if (!CLOCK.test(value)) return value;
    const m = minutes(value);
    return m === 0 ? "12 am (midnight)" : spoken(m);
}

function join(items: string[]): string {
    if (items.length <= 1) return items.join("");
    return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

function daysPhrase(days: number[]): string {
    if (days.length === 7) return "every day";
    const runs: number[][] = [];
    for (const day of [...days].sort((a, b) => a - b)) {
        const last = runs[runs.length - 1];
        if (last && day === last[last.length - 1] + 1) last.push(day);
        else runs.push([day]);
    }
    return join(
        runs.flatMap((run) =>
            run.length >= 3 ? [`${DAY_LONG[run[0]]} to ${DAY_LONG[run[run.length - 1]]}`] : run.map((d) => DAY_LONG[d]),
        ),
    );
}

const rangesKey = (ranges: OpenRange[]) => ranges.map((r) => `${r.open}-${r.close}`).join(",");

/**
 * What the agent tells callers, generated from the times as the server
 * does: "Tuesday to Sunday 12 to 3 pm and 5 to 10 pm, closed Monday".
 */
export function describeOpeningHours(hours: OpeningHours): string {
    const groups = new Map<string, { ranges: OpenRange[]; days: number[] }>();
    const closed: number[] = [];
    weekOf(hours).forEach((ranges, day) => {
        if (ranges.length === 0) {
            closed.push(day);
            return;
        }
        const key = rangesKey(ranges);
        const group = groups.get(key) ?? { ranges, days: [] };
        group.days.push(day);
        groups.set(key, group);
    });
    const phrases = [...groups.values()].map((g) => `${daysPhrase(g.days)} ${join(g.ranges.map(spokenRange))}`);
    if (closed.length) phrases.push(`closed ${daysPhrase(closed)}`);
    let text = phrases.join(", ");
    text = text.charAt(0).toUpperCase() + text.slice(1);
    const note = (hours.note ?? "").split(/\s+/).filter(Boolean).join(" ");
    if (note) text = `${text}. ${note.charAt(0).toUpperCase()}${note.slice(1)}`;
    return text;
}

/** One chip per weekday: the hours, or null when closed. */
export function dayChips(hours: OpeningHours): { short: string; long: string; lines: string[] | null }[] {
    return weekOf(hours).map((ranges, day) => ({
        short: DAY_SHORT[day],
        long: DAY_LONG[day],
        lines: ranges.length ? ranges.map(rangeLabel) : null,
    }));
}

/** Why the hours can't be saved, in the owner's words; null when they can. */
export function openingHoursProblem(hours: OpeningHours): string | null {
    const week = weekOf(hours);
    for (let day = 0; day < 7; day++) {
        const ranges = week[day];
        if (ranges.length > MAX_RANGES_PER_DAY) return `${DAY_LONG[day]}: at most ${MAX_RANGES_PER_DAY} opening times.`;
        let previousEnd = -1;
        for (let i = 0; i < ranges.length; i++) {
            const range = ranges[i];
            if (!CLOCK.test(range.open) || !CLOCK.test(range.close)) return `${DAY_LONG[day]}: choose a time.`;
            const [start, end] = span(range);
            if (start <= previousEnd) {
                return `${DAY_LONG[day]}: the opening times overlap or are out of order.`;
            }
            if (end > DAY && i !== ranges.length - 1) {
                return `${DAY_LONG[day]}: only the last opening time can run past midnight.`;
            }
            previousEnd = end;
        }
    }
    if ((hours.note ?? "").length > MAX_NOTE_LENGTH) return `The note is too long (at most ${MAX_NOTE_LENGTH} characters).`;
    return null;
}

/** Whether a range runs past midnight into the next day. */
export function isOvernight(range: OpenRange): boolean {
    return span(range)[1] > DAY;
}

/** A sensible next range for a day: an hour after its last one, else 9 to 5; null when the day is full. */
export function nextRange(ranges: OpenRange[]): OpenRange | null {
    const last = ranges[ranges.length - 1];
    if (!last) return { open: "09:00", close: "17:00" };
    const end = span(last)[1];
    if (end >= DAY - 60) return null;
    const open = end + 60;
    return { open: clock(open), close: clock(Math.min(open + 180, DAY)) };
}

/** Same schedule, field by field (null is "no times set"). */
export function sameOpeningHours(a: OpeningHours | null | undefined, b: OpeningHours | null | undefined): boolean {
    if (!a || !b) return !a && !b;
    return (
        (a.timezone ?? "Europe/Dublin") === (b.timezone ?? "Europe/Dublin") &&
        (a.transfer_only_when_open ?? true) === (b.transfer_only_when_open ?? true) &&
        (a.note ?? "") === (b.note ?? "") &&
        weekOf(a).every((ranges, day) => rangesKey(ranges) === rangesKey(weekOf(b)[day]))
    );
}

/** The hours as the API takes them: empty note as null. */
export function forSave(hours: OpeningHours): OpeningHours {
    const note = (hours.note ?? "").trim();
    return { ...hours, days: weekOf(hours) as OpeningHours["days"], note: note || null };
}
