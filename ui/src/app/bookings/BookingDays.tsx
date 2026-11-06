import { Phone, Users } from "lucide-react";

import type { CalendarBooking } from "@/client/types.gen";
import { StatusPill } from "@/components/ui/status-pill";
import { cn } from "@/lib/utils";

import {
    bookedOn,
    type CalendarDay,
    daySummary,
    partyLabel,
    startTime,
    telHref,
    untilTime,
} from "./bookingsView";

/**
 * The bookings, one block per day. Quiet days stay in the list, so an owner
 * can see at a glance that Tuesday is empty rather than wonder if it loaded.
 */
export function BookingDays({
    days,
    calendarNames,
}: {
    days: CalendarDay[];
    /** Calendar names by connection, only when there is more than one calendar. */
    calendarNames?: Map<string, string>;
}) {
    return (
        <ol className="flex flex-col gap-5" aria-label="Bookings by day">
            {days.map((day) => {
                const headingId = `day-${day.key}`;
                const isToday = day.label.startsWith("Today");
                return (
                    <li key={day.key} aria-labelledby={headingId}>
                        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 border-b border-line-soft pb-1.5">
                            <h3 id={headingId} className="flex items-center gap-2 text-[15px] font-semibold">
                                {isToday && <span className="size-2 rounded-full bg-brand" aria-hidden />}
                                {day.label}
                            </h3>
                            <span className="text-[13px] text-ink-3">
                                {day.confirmed > 0 ? daySummary(day) : null}
                                {day.hiddenCancelled > 0 &&
                                    `${day.confirmed > 0 ? " · " : ""}${day.hiddenCancelled} cancelled`}
                            </span>
                        </div>
                        {day.bookings.length === 0 ? (
                            <p className="rounded-lg border border-dashed border-line px-4 py-2.5 text-sm text-ink-3">
                                No bookings
                            </p>
                        ) : (
                            <ul className="flex flex-col gap-2">
                                {day.bookings.map((booking) => (
                                    <BookingCard
                                        key={`${booking.connection_id}-${booking.event_id}`}
                                        booking={booking}
                                        calendarName={calendarNames?.get(booking.connection_id)}
                                    />
                                ))}
                            </ul>
                        )}
                    </li>
                );
            })}
        </ol>
    );
}

export function BookingCard({ booking, calendarName }: { booking: CalendarBooking; calendarName?: string }) {
    const cancelled = booking.status === "cancelled";
    const party = partyLabel(booking);
    const made = bookedOn(booking);
    const name = booking.caller_name || "Name not given";
    return (
        <li
            className={cn(
                "flex gap-4 rounded-lg border px-4 py-3",
                cancelled ? "border-dashed border-line bg-panel-2" : "border-line bg-panel",
            )}
        >
            <div className="w-14 flex-none pt-0.5">
                <div
                    className={cn(
                        "font-mono text-base font-semibold tabular-nums",
                        cancelled ? "text-ink-3 line-through" : "text-foreground",
                    )}
                >
                    {startTime(booking)}
                </div>
                <div className="text-xs text-ink-3">{untilTime(booking)}</div>
            </div>

            <div className="flex min-w-0 flex-1 flex-col gap-2 sm:flex-row sm:items-center sm:gap-6">
                <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span
                            className={cn(
                                "font-semibold",
                                cancelled && "text-ink-3 line-through",
                                !booking.caller_name && "font-normal text-ink-3",
                            )}
                        >
                            {name}
                        </span>
                        <StatusPill tone={cancelled ? "mute" : "ok"}>{cancelled ? "Cancelled" : "Booked"}</StatusPill>
                    </div>
                    {booking.reason && <p className="mt-0.5 text-sm text-ink-2">{booking.reason}</p>}
                    <p className="mt-0.5 text-xs text-ink-3">
                        Booked by your agent{made ? ` on ${made}` : ""}
                        {calendarName ? ` · ${calendarName}` : ""}
                    </p>
                </div>

                <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                    <span
                        className={cn(
                            "inline-flex items-center gap-1.5 text-sm sm:w-24",
                            party === "Not asked" ? "text-ink-3" : "text-foreground",
                        )}
                    >
                        <Users className="size-4 flex-none text-ink-3" aria-hidden />
                        <span>
                            {party === "Not asked" ? <span className="sr-only">Party size: </span> : null}
                            {party}
                        </span>
                    </span>
                    {booking.caller_phone ? (
                        <a
                            className="inline-flex min-h-10 items-center gap-1.5 rounded-md border border-line px-3 font-mono text-sm text-foreground transition-colors hover:border-brand/50 hover:bg-brand-dim hover:text-brand focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40 motion-reduce:transition-none sm:min-h-9"
                            href={telHref(booking.caller_phone)}
                            aria-label={`Call ${name} on ${booking.caller_phone}`}
                        >
                            <Phone className="size-3.5 flex-none" aria-hidden />
                            {booking.caller_phone}
                        </a>
                    ) : (
                        <span className="text-sm text-ink-3">No phone number</span>
                    )}
                </div>
            </div>
        </li>
    );
}
