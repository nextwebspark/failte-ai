import { addDays, format, isSameDay, startOfDay } from "date-fns";

import type { CalendarBooking } from "@/client/types.gen";

/** The ranges the Bookings screen offers; the API allows up to 62 days. */
export type RangeKey = "next7" | "next14" | "past7";

export const RANGE_OPTIONS: { value: RangeKey; label: string }[] = [
    { value: "next7", label: "Next 7 days" },
    { value: "next14", label: "Next 14 days" },
    { value: "past7", label: "Last 7 days" },
];

export function rangeFor(key: RangeKey, now: Date): { start: Date; end: Date } {
    const today = startOfDay(now);
    if (key === "past7") return { start: addDays(today, -7), end: today };
    return { start: today, end: addDays(today, key === "next14" ? 14 : 7) };
}

/** ISO 8601 with the browser's offset, as the API requires. */
export function isoWithOffset(date: Date): string {
    return format(date, "yyyy-MM-dd'T'HH:mm:ssxxx");
}

export interface DayGroup {
    key: string;
    label: string;
    bookings: CalendarBooking[];
    /** Guests across the day's confirmed bookings that have a party size. */
    guests: number;
    confirmed: number;
}

export function dayLabel(day: Date, now: Date): string {
    if (isSameDay(day, now)) return `Today · ${format(day, "EEE d MMM")}`;
    if (isSameDay(day, addDays(now, 1))) return `Tomorrow · ${format(day, "EEE d MMM")}`;
    return format(day, "EEEE d MMMM");
}

/** Bookings by local day, in start order (the API already sorts by start). */
export function groupByDay(
    bookings: CalendarBooking[],
    now: Date,
    showCancelled: boolean,
): DayGroup[] {
    const groups = new Map<string, DayGroup>();
    for (const booking of bookings) {
        if (!showCancelled && booking.status === "cancelled") continue;
        const start = new Date(booking.start);
        const key = format(start, "yyyy-MM-dd");
        let group = groups.get(key);
        if (!group) {
            group = { key, label: dayLabel(start, now), bookings: [], guests: 0, confirmed: 0 };
            groups.set(key, group);
        }
        group.bookings.push(booking);
        if (booking.status === "confirmed") {
            group.confirmed += 1;
            group.guests += booking.party_size ?? 0;
        }
    }
    return [...groups.values()];
}

/** "4 guests", "1 guest", or "Not asked" when the agent did not take a party size. */
export function partyLabel(booking: Pick<CalendarBooking, "party_size">): string {
    const size = booking.party_size;
    if (size === null || size === undefined) return "Not asked";
    return size === 1 ? "1 guest" : `${size} guests`;
}

export function timeRange(booking: Pick<CalendarBooking, "start" | "end">): string {
    return `${format(new Date(booking.start), "HH:mm")}–${format(new Date(booking.end), "HH:mm")}`;
}

export interface BookingTotals {
    confirmed: number;
    cancelled: number;
    /** Guests on confirmed bookings with a party size. */
    guests: number;
    /** Confirmed bookings with no party size (the agent did not ask). */
    noPartySize: number;
}

export function totals(bookings: CalendarBooking[]): BookingTotals {
    const result: BookingTotals = { confirmed: 0, cancelled: 0, guests: 0, noPartySize: 0 };
    for (const booking of bookings) {
        if (booking.status === "cancelled") {
            result.cancelled += 1;
            continue;
        }
        result.confirmed += 1;
        if (booking.party_size === null || booking.party_size === undefined) result.noPartySize += 1;
        else result.guests += booking.party_size;
    }
    return result;
}

export interface CalendarDay extends DayGroup {
    date: Date;
    /** Cancelled bookings on this day that are hidden (Show cancelled is off). */
    hiddenCancelled: number;
}

/**
 * Every day in [start, end), each with its bookings, so a quiet day still shows
 * as a day rather than vanishing from the list. A booking outside the range (an
 * event that started the day before and runs past midnight) goes on its own day.
 */
export function daysInRange(
    bookings: CalendarBooking[],
    range: { start: Date; end: Date },
    now: Date,
    showCancelled: boolean,
): CalendarDay[] {
    const days = new Map<string, CalendarDay>();
    const add = (date: Date) => {
        const key = format(date, "yyyy-MM-dd");
        let day = days.get(key);
        if (!day) {
            day = {
                key,
                date: startOfDay(date),
                label: dayLabel(date, now),
                bookings: [],
                guests: 0,
                confirmed: 0,
                hiddenCancelled: 0,
            };
            days.set(key, day);
        }
        return day;
    };
    for (let day = startOfDay(range.start); day < range.end; day = addDays(day, 1)) add(day);
    for (const booking of bookings) {
        const day = add(new Date(booking.start));
        if (booking.status === "cancelled") {
            if (showCancelled) day.bookings.push(booking);
            else day.hiddenCancelled += 1;
            continue;
        }
        day.bookings.push(booking);
        day.confirmed += 1;
        day.guests += booking.party_size ?? 0;
    }
    return [...days.values()].sort((a, b) => a.date.getTime() - b.date.getTime());
}

/** "19:30", the start time on its own, for the big time on a booking. */
export function startTime(booking: Pick<CalendarBooking, "start">): string {
    return format(new Date(booking.start), "HH:mm");
}

/** "until 21:00". */
export function untilTime(booking: Pick<CalendarBooking, "end">): string {
    return `until ${format(new Date(booking.end), "HH:mm")}`;
}

/** "Mon 2 Nov, 14:05": when the booking was made, if the calendar says. */
export function bookedOn(booking: Pick<CalendarBooking, "created_at">): string | null {
    if (!booking.created_at) return null;
    const made = new Date(booking.created_at);
    if (Number.isNaN(made.getTime())) return null;
    return format(made, "EEE d MMM, HH:mm");
}

/** The tel: link for a phone number as callers gave it ("087 123 4567"). */
export function telHref(phone: string): string {
    return `tel:${phone.replace(/[^\d+]/g, "")}`;
}

/** "3 bookings · 9 guests", leaving out guests when nobody gave a party size. */
export function daySummary(day: Pick<DayGroup, "confirmed" | "guests">): string {
    const bookings = `${day.confirmed} ${day.confirmed === 1 ? "booking" : "bookings"}`;
    if (day.guests === 0) return bookings;
    return `${bookings} · ${day.guests} ${day.guests === 1 ? "guest" : "guests"}`;
}

export interface FriendlyError {
    title: string;
    body: string;
    /** False when trying again won't help (the feature isn't switched on). */
    retry: boolean;
}

/**
 * What an owner reads when bookings can't be loaded. Never the server's own
 * words: the codes only pick which plain message to show.
 */
export function bookingsLoadError(code: string | undefined): FriendlyError {
    if (code === "integration_unavailable" || code === "tools_service_not_configured") {
        return {
            title: "Bookings aren't switched on for your account yet",
            body: "Ask your LightMove contact to turn them on.",
            retry: false,
        };
    }
    return {
        title: "Bookings aren't available right now",
        body: "We're on it. Try again in a minute.",
        retry: true,
    };
}
