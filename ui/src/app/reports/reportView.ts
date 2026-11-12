/**
 * Words and small sums for the Reports page. Pure: no React, no fetching.
 */
import type { ReportCardView, ReportOverviewResponse, ReportRange } from "@/client/types.gen";

export const RANGE_OPTIONS: { value: ReportRange; label: string }[] = [
    { value: "today", label: "Today" },
    { value: "7d", label: "7 days" },
    { value: "30d", label: "30 days" },
    { value: "custom", label: "Custom" },
];

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parts(date: Date, timezone: string, options: Intl.DateTimeFormatOptions) {
    const found = new Intl.DateTimeFormat("en-IE", { timeZone: timezone, ...options }).formatToParts(date);
    return (type: string) => found.find((p) => p.type === type)?.value ?? "";
}

/** "5pm", "11am", "12pm": an hour on an axis. */
export function shortHour(hour: number): string {
    const h = ((hour % 24) + 24) % 24;
    return `${h % 12 || 12}${h < 12 ? "am" : "pm"}`;
}

/** "5–7 pm", "11 am–1 pm": a span of hours in words. */
export function hourRange(start: number, end: number): string {
    const a = ((start % 24) + 24) % 24;
    const b = ((end % 24) + 24) % 24;
    const sa = a < 12 ? "am" : "pm";
    const sb = b < 12 ? "am" : "pm";
    if (sa === sb) return `${a % 12 || 12}–${b % 12 || 12} ${sb}`;
    return `${a % 12 || 12} ${sa}–${b % 12 || 12} ${sb}`;
}

/** "Sat 1" from an ISO day ("2026-11-01"), read as a calendar day. */
export function shortDay(iso: string): string {
    const [y, m, d] = iso.split("-").map(Number);
    const day = new Date(Date.UTC(y, m - 1, d));
    return `${WEEKDAYS[(day.getUTCDay() + 6) % 7].slice(0, 3)} ${d}`;
}

/** "1–7 Nov", "28 Oct – 3 Nov", "7 Nov": the days a report covers. */
export function spanWords(startIso: string, endIso: string, timezone: string): string {
    const start = new Date(startIso);
    // The end is exclusive: the last moment counted is just before it.
    const last = new Date(new Date(endIso).getTime() - 1);
    const a = parts(start, timezone, { day: "numeric", month: "numeric", year: "numeric" });
    const b = parts(last, timezone, { day: "numeric", month: "numeric", year: "numeric" });
    const [ad, am, ay] = [Number(a("day")), Number(a("month")), Number(a("year"))];
    const [bd, bm, by] = [Number(b("day")), Number(b("month")), Number(b("year"))];
    if (ad === bd && am === bm && ay === by) return `${ad} ${MONTHS[am - 1]}`;
    if (am === bm && ay === by) return `${ad}–${bd} ${MONTHS[bm - 1]}`;
    if (ay === by) return `${ad} ${MONTHS[am - 1]} – ${bd} ${MONTHS[bm - 1]}`;
    return `${ad} ${MONTHS[am - 1]} ${ay} – ${bd} ${MONTHS[bm - 1]} ${by}`;
}

/** The page's headline: "Last 7 days, 1–7 Nov", "Today, 7 Nov". */
export function reportTitle(report: Pick<ReportOverviewResponse, "range" | "start" | "end" | "timezone">): string {
    const span = spanWords(report.start, report.end, report.timezone);
    if (report.range === "today") return `Today, ${span}`;
    if (report.range === "7d") return `Last 7 days, ${span}`;
    if (report.range === "30d") return `Last 30 days, ${span}`;
    return span;
}

/** What the change is measured against, in words. */
export function comparedWith(report: Pick<ReportOverviewResponse, "range" | "start" | "end" | "previous_start" | "timezone">): string {
    if (report.range === "today") {
        const weekday = parts(new Date(report.start), report.timezone, { weekday: "long" })("weekday");
        return `the same time last ${weekday}`;
    }
    if (report.range === "7d") return "the 7 days before";
    if (report.range === "30d") return "the 30 days before";
    return `${spanWords(report.previous_start, report.start, report.timezone)}, the same length before`;
}

/** The chip under a headline number: "↑ 14 on last week"; null when hidden. */
export function changeChip(
    change: number | null | undefined,
    unit = "",
): { tone: "up" | "down" | "same"; text: string } | null {
    if (change == null) return null;
    if (change === 0) return { tone: "same", text: "Same as before" };
    const amount = `${Math.abs(change).toLocaleString("en-IE")}${unit}`;
    return change > 0 ? { tone: "up", text: `↑ ${amount}` } : { tone: "down", text: `↓ ${amount}` };
}

export function plural(count: number, one: string, many = `${one}s`): string {
    return `${count.toLocaleString("en-IE")} ${count === 1 ? one : many}`;
}

/** "€4,970", "€35.50". */
export function money(value: string | number): string {
    const amount = typeof value === "string" ? Number(value) : value;
    const whole = Number.isInteger(amount);
    return new Intl.NumberFormat("en-IE", {
        style: "currency",
        currency: "EUR",
        minimumFractionDigits: whole ? 0 : 2,
        maximumFractionDigits: 2,
    }).format(amount);
}

/** "142 covers × your €35 average spend". */
export function estimateFormula(units: number, unit: string, average: string | number): string {
    const what = unit === "cover" ? "average spend" : "average value";
    return `${plural(units, unit)} × your ${money(average)} ${what}`;
}

/** "Mostly Fri and Sat, 8–9 pm"; null when nothing stands out. */
export function mostlyWords(days: number[], hour: number | null | undefined): string | null {
    const names = days.map((d) => WEEKDAYS[d].slice(0, 3));
    const dayText = names.length === 2 ? `${names[0]} and ${names[1]}` : names.join("");
    const hourText = hour == null ? "" : hourRange(hour, hour + 1);
    if (!dayText && !hourText) return null;
    return `Mostly ${[dayText, hourText].filter(Boolean).join(", ")}`;
}

/** The busiest-times tip, word for word. */
export function tipWords(
    tip: { weekday: number; start_hour: number; end_hour: number; one_in: number },
    days: number,
): string {
    const day = WEEKDAYS[tip.weekday];
    const when = `${days > 7 ? `${day}s` : day} ${hourRange(tip.start_hour, tip.end_hour)}`;
    const share = tip.one_in <= 1 ? "most" : `1 in ${tip.one_in}`;
    return `${when} takes ${share} of your calls. Worth having someone free to answer transfers then.`;
}

/** A cell's shade in the heatmap: 0 (no calls) to 5 (the busiest). */
export function heatLevel(count: number, max: number): number {
    if (count <= 0 || max <= 0) return 0;
    return Math.max(1, Math.min(5, Math.ceil((count / max) * 5)));
}

/** A round top for an axis: 2, 4, 5, 10, 15, 20, 30, 40, 50, 75, 100 … */
export function niceMax(value: number): number {
    if (value <= 2) return 2;
    if (value <= 4) return 4;
    if (value <= 5) return 5;
    const step = value <= 20 ? 5 : value <= 50 ? 10 : value <= 100 ? 25 : 50;
    return Math.ceil(value / step) * step;
}

/** Move one item up or down a list (a new list; out of range: unchanged). */
export function moveItem<T>(items: T[], from: number, to: number): T[] {
    if (from === to || from < 0 || to < 0 || from >= items.length || to >= items.length) return items;
    const next = [...items];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    return next;
}

/** The cards shown: switched on, and, for a money estimate, only with an average. */
export function shownCards(cards: ReportCardView[], average: string | null | undefined): ReportCardView[] {
    return cards.filter((c) => c.on && (!c.estimate || Boolean(average && Number(average) > 0)));
}

/** "2026-11-07" in the business's zone. */
export function isoDay(date: Date, timezone: string): string {
    const p = parts(date, timezone, { year: "numeric", month: "2-digit", day: "2-digit" });
    return `${p("year")}-${p("month")}-${p("day")}`;
}
