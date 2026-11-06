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
