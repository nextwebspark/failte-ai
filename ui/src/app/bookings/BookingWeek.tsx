import { format } from "date-fns";

import type { CalendarBooking } from "@/client/types.gen";
import { cn } from "@/lib/utils";

import { type CalendarDay, partyLabel, timeRange } from "./bookingsView";

const HOUR_PX = 44;

/** The hours the grid shows: 8 am to 10 pm, wider when a booking falls outside. */
export function gridHours(days: CalendarDay[]): { first: number; last: number } {
    let first = 8;
    let last = 22;
    for (const day of days) {
        for (const booking of day.bookings) {
            const start = new Date(booking.start);
            const end = new Date(booking.end);
            first = Math.min(first, start.getHours());
            last = Math.max(last, end.getHours() + (end.getMinutes() > 0 ? 1 : 0));
        }
    }
    return { first, last: Math.min(Math.max(last, first + 1), 24) };
}

/** Where a booking sits in its day column, in pixels from the first hour. */
export function blockPosition(
    booking: Pick<CalendarBooking, "start" | "end">,
    firstHour: number,
): { top: number; height: number } {
    const start = new Date(booking.start);
    const end = new Date(booking.end);
    const minutes = (d: Date) => d.getHours() * 60 + d.getMinutes();
    const top = ((minutes(start) - firstHour * 60) / 60) * HOUR_PX;
    const length = Math.max(minutes(end) - minutes(start), 15);
    return { top, height: Math.max((length / 60) * HOUR_PX, 22) };
}

function chunk<T>(items: T[], size: number): T[][] {
    const out: T[][] = [];
    for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
    return out;
}

/**
 * The bookings on a week grid: a column per day, an hour per row, each
 * booking a block from its start to its end. It shows what is booked; free
 * times are whatever the calendar has left around them.
 */
export function BookingWeek({ days }: { days: CalendarDay[] }) {
    const { first, last } = gridHours(days);
    const hours = Array.from({ length: last - first }, (_, i) => first + i);
    return (
        <div className="flex flex-col gap-6">
            {chunk(days, 7).map((week) => (
                <div
                    key={week[0]?.key}
                    className="overflow-x-auto rounded-xl border border-line bg-panel"
                    role="group"
                    aria-label={`Week of ${week[0] ? format(week[0].date, "d MMMM") : ""}`}
                >
                    <div className="grid min-w-[560px]" style={{ gridTemplateColumns: `44px repeat(${week.length}, minmax(0, 1fr))` }}>
                        <div className="border-b border-line" />
                        {week.map((day) => (
                            <div
                                key={day.key}
                                className={cn(
                                    "border-b border-l border-line px-1 py-2 text-center",
                                    day.label.startsWith("Today") && "bg-brand-dim",
                                )}
                            >
                                <p className="text-caption font-medium text-ink-3">{format(day.date, "EEE")}</p>
                                <p className="font-display text-body font-semibold">{format(day.date, "d MMM")}</p>
                                <p className="text-caption text-ink-3">
                                    {day.confirmed === 0 ? "No bookings" : day.confirmed === 1 ? "1 booking" : `${day.confirmed} bookings`}
                                </p>
                            </div>
                        ))}

                        <div className="relative" style={{ height: hours.length * HOUR_PX }}>
                            {hours.map((hour, i) => (
                                <span
                                    key={hour}
                                    className="absolute right-1.5 -translate-y-1/2 text-[11px] tabular-nums text-ink-3"
                                    style={{ top: i * HOUR_PX }}
                                >
                                    {i === 0 ? "" : `${String(hour).padStart(2, "0")}:00`}
                                </span>
                            ))}
                        </div>
                        {week.map((day) => (
                            <ol
                                key={day.key}
                                className="relative border-l border-line"
                                style={{
                                    height: hours.length * HOUR_PX,
                                    backgroundImage: `repeating-linear-gradient(to bottom, transparent 0, transparent ${HOUR_PX - 1}px, var(--color-line-soft, rgba(0,0,0,0.06)) ${HOUR_PX - 1}px, var(--color-line-soft, rgba(0,0,0,0.06)) ${HOUR_PX}px)`,
                                }}
                                aria-label={`${format(day.date, "EEEE d MMMM")}: ${day.confirmed} booked`}
                            >
                                {day.bookings.map((booking) => {
                                    const { top, height } = blockPosition(booking, first);
                                    const cancelled = booking.status === "cancelled";
                                    const party = booking.party_size ? partyLabel(booking) : null;
                                    return (
                                        <li
                                            key={`${booking.connection_id}-${booking.event_id}`}
                                            className={cn(
                                                "absolute inset-x-1 overflow-hidden rounded-md border px-1.5 py-1 text-[12px] leading-tight",
                                                cancelled
                                                    ? "border-line bg-panel-2 text-ink-3 line-through"
                                                    : "border-brand/40 bg-brand-dim text-foreground",
                                            )}
                                            style={{ top, height }}
                                            title={`${timeRange(booking)} · ${booking.caller_name ?? "No name"}${party ? ` · ${party}` : ""}${booking.caller_phone ? ` · ${booking.caller_phone}` : ""}`}
                                        >
                                            {height < 40 ? (
                                                // A short booking: time and name on one line.
                                                <span className="block truncate">
                                                    <span className="font-semibold tabular-nums">
                                                        {format(new Date(booking.start), "HH:mm")}
                                                    </span>{" "}
                                                    {booking.caller_name ?? "No name"}
                                                    {party ? ` · ${party}` : ""}
                                                </span>
                                            ) : (
                                                <>
                                                    <span className="block font-semibold tabular-nums">{timeRange(booking)}</span>
                                                    <span className="block truncate">
                                                        {booking.caller_name ?? "No name"}
                                                        {party ? ` · ${party}` : ""}
                                                    </span>
                                                </>
                                            )}
                                        </li>
                                    );
                                })}
                            </ol>
                        ))}
                    </div>
                </div>
            ))}
        </div>
    );
}
