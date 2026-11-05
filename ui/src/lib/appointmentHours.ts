import type { AppointmentHours, SetupFieldType, TemplateSetupField, Weekday } from '@/client/types.gen';

/** A template question answered with structured hours, not text. */
export const APPOINTMENT_HOURS_TYPE: SetupFieldType = 'appointment_hours';

/** Every field set: what the dialog edits and sends. */
export type BookingHours = Required<AppointmentHours>;

/** The time zone when this browser can't say its own. */
export const DEFAULT_TIMEZONE = 'Europe/Dublin';

export const WEEKDAYS: { value: Weekday; short: string; long: string }[] = [
    { value: 0, short: 'Mon', long: 'Monday' },
    { value: 1, short: 'Tue', long: 'Tuesday' },
    { value: 2, short: 'Wed', long: 'Wednesday' },
    { value: 3, short: 'Thu', long: 'Thursday' },
    { value: 4, short: 'Fri', long: 'Friday' },
    { value: 5, short: 'Sat', long: 'Saturday' },
    { value: 6, short: 'Sun', long: 'Sunday' },
];

/** Appointment lengths offered, in minutes. */
export const SLOT_MINUTES = [15, 30, 45, 60, 90];

/** Whole hours, as the calendar connection takes them: opening 0–23, closing 1–24. */
export const OPEN_HOURS = Array.from({ length: 24 }, (_, hour) => hour);
export const CLOSE_HOURS = Array.from({ length: 24 }, (_, hour) => hour + 1);

export function isAppointmentHoursField(field: TemplateSetupField): boolean {
    return field.type === APPOINTMENT_HOURS_TYPE;
}

/** "09:00", "24:00". */
export function hourLabel(hour: number): string {
    return `${String(hour).padStart(2, '0')}:00`;
}

/** "30 min", "1 h 30 min". */
export function slotLabel(minutes: number): string {
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    if (!hours) return `${rest} min`;
    return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

/** The IANA time zones this browser knows, or null when it can't list them. */
function supportedTimeZones(): string[] | null {
    try {
        return typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : null;
    } catch {
        return null;
    }
}

/**
 * This browser's time zone, else Europe/Dublin: also when it isn't a real
 * zone (e.g. "Etc/Unknown"). The browser's zone list leaves out UTC.
 */
export function browserTimeZone(): string {
    let zone: string;
    try {
        zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    } catch {
        return DEFAULT_TIMEZONE;
    }
    const known = supportedTimeZones();
    if (!zone || (known && zone !== 'UTC' && !known.includes(zone))) return DEFAULT_TIMEZONE;
    return zone;
}

/** The time zones to choose from, always including *current*. */
export function timeZoneOptions(current: string): string[] {
    const zones = supportedTimeZones() ?? [DEFAULT_TIMEZONE, 'UTC'];
    return zones.includes(current) ? zones : [current, ...zones];
}

/** Monday to Friday, 9:00–17:00, 30 minutes, in this browser's time zone. */
export function defaultBookingHours(): BookingHours {
    return {
        booking_days: [0, 1, 2, 3, 4],
        open_hour: 9,
        close_hour: 17,
        slot_minutes: 30,
        timezone: browserTimeZone(),
    };
}

function wholeNumber(value: unknown, min: number, max: number): number | null {
    return typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max ? value : null;
}

/**
 * The hours a Google Calendar connection already books in, from its stored
 * settings (time zone included); a missing or invalid setting keeps the
 * dialog's default.
 */
export function bookingHoursFromConfig(config: Record<string, unknown> | undefined): BookingHours {
    const hours = defaultBookingHours();
    if (!config) return hours;
    const days = config.booking_days;
    if (Array.isArray(days)) {
        const valid = days.filter((day): day is Weekday => wholeNumber(day, 0, 6) !== null);
        if (valid.length > 0) hours.booking_days = [...new Set(valid)].sort((a, b) => a - b);
    }
    hours.open_hour = wholeNumber(config.open_hour, 0, 23) ?? hours.open_hour;
    hours.close_hour = wholeNumber(config.close_hour, 1, 24) ?? hours.close_hour;
    hours.slot_minutes = wholeNumber(config.slot_minutes, 5, 240) ?? hours.slot_minutes;
    if (typeof config.timezone === 'string' && config.timezone) hours.timezone = config.timezone;
    return hours;
}

/** What is wrong with *hours* (the server checks the same), or null. */
export function bookingHoursProblem(hours: BookingHours): string | null {
    if (hours.booking_days.length === 0) return 'Pick at least one day.';
    if (hours.open_hour >= hours.close_hour) return 'The closing time must be after the opening time.';
    if ((hours.close_hour - hours.open_hour) * 60 < hours.slot_minutes) {
        return 'An appointment is longer than these hours.';
    }
    return null;
}
