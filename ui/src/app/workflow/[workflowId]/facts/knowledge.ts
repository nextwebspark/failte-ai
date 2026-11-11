/**
 * Pure helpers behind "What your agent knows": they read the agent's stored
 * definition and settings so the page only shows what is really there.
 */

type Node = { type?: string; data?: Record<string, unknown> };
type Definition = { nodes?: Node[] } | null | undefined;

/** The Google Calendar integration's provider id, in its MCP address. */
export const GOOGLE_CALENDAR_PROVIDER = "google-calendar";

function nodes(definition: unknown): Node[] {
  const list = (definition as Definition)?.nodes;
  return Array.isArray(list) ? list : [];
}

/** Every tool the agent's steps can use. */
export function attachedToolUuids(definition: unknown): Set<string> {
  const uuids = new Set<string>();
  for (const node of nodes(definition)) {
    const list = node.data?.tool_uuids;
    if (Array.isArray(list)) {
      for (const uuid of list) if (typeof uuid === "string") uuids.add(uuid);
    }
  }
  return uuids;
}

export type Greeting = { kind: "text"; text: string } | { kind: "recording" } | null;

/**
 * What callers hear first: the start step's greeting. A spoken greeting is
 * returned as written (placeholders and all); a recorded one only as such.
 */
export function startGreeting(definition: unknown): Greeting {
  const start = nodes(definition).find((node) => node.data?.is_start === true || node.type === "startCall");
  const data = start?.data;
  if (!data) return null;
  if (data.greeting_type === "audio" && data.greeting_recording_id) return { kind: "recording" };
  const text = typeof data.greeting === "string" ? data.greeting.trim() : "";
  return text ? { kind: "text", text } : null;
}

/**
 * Fill a greeting's `{{initial_context.key}}` placeholders from the facts on
 * screen, so it reads as callers hear it. An unknown or empty one is left
 * out; anything else in braces is shown as written.
 */
export function fillGreeting(text: string, facts: Record<string, string>): string {
  return text
    .replace(/\{\{\s*initial_context\.([a-z][a-z0-9_]*)\s*\}\}/gi, (_, key: string) => (facts[key] ?? "").trim())
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\s+([,.!?])/g, "$1")
    .trim();
}

/** Whether a tool is the Google Calendar integration (an MCP tool at its address). */
export function isCalendarTool(tool: { category?: string; definition?: unknown }): boolean {
  if (tool.category !== "mcp") return false;
  const url = (tool.definition as { config?: { url?: unknown } } | undefined)?.config?.url;
  return typeof url === "string" && url.includes(GOOGLE_CALENDAR_PROVIDER);
}

/** One stretch of the week bookings may start in, as the calendar stores it. */
export type ServicePeriod = { days: number[]; first_start: string; last_start: string };

const CLOCK = /^([01]\d|2[0-3]):([0-5]\d)$/;

/** "17:00" → "5 pm", "12:30" → "12:30 pm" (Irish/UK style). */
export function clockLabel(value: string): string {
  const match = CLOCK.exec(value);
  if (!match) return value;
  const hour = Number(match[1]);
  const minute = match[2];
  const suffix = hour < 12 ? "am" : "pm";
  const h12 = hour % 12 === 0 ? 12 : hour % 12;
  return minute === "00" ? `${h12} ${suffix}` : `${h12}:${minute} ${suffix}`;
}

export const WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;
export const WEEK_LONG = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"] as const;

/**
 * The calendar's booking windows per weekday (Monday first): each window is
 * when the first and the last booking may start. Null when there are none.
 */
export function bookingTimesByDay(rules: unknown): string[][] | null {
  const periods = (rules as { service_periods?: unknown } | null | undefined)?.service_periods;
  if (!Array.isArray(periods) || periods.length === 0) return null;
  const week: { start: string; text: string }[][] = WEEK.map(() => []);
  for (const raw of periods) {
    const period = raw as Partial<ServicePeriod> | null;
    if (!period || !Array.isArray(period.days)) continue;
    const { first_start: first, last_start: last } = period;
    if (typeof first !== "string" || typeof last !== "string" || !CLOCK.test(first) || !CLOCK.test(last)) continue;
    for (const day of period.days) {
      if (Number.isInteger(day) && day >= 0 && day <= 6) {
        week[day].push({ start: first, text: `${clockLabel(first)}–${clockLabel(last)}` });
      }
    }
  }
  if (week.every((day) => day.length === 0)) return null;
  return week.map((day) => day.sort((a, b) => a.start.localeCompare(b.start)).map((w) => w.text));
}
