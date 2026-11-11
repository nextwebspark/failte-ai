import type { AppointmentHours, SetupFieldType, TemplateSetupField, Weekday } from '@/client/types.gen';

/** A template question answered with structured hours, not text. */
export const APPOINTMENT_HOURS_TYPE: SetupFieldType = 'appointment_hours';

/** Every field set: what the dialog edits and sends. */
export type BookingHours = Required<AppointmentHours>;

/**
 * The Google Calendar connection's default time zone, and the one used when
 * this browser can't say its own.
 */
export const DEFAULT_TIMEZONE = 'Europe/Dublin';

/**
 * The connection settings that hold its booking hours. `service_periods`
 * (what this dialog saves, and what the Bookings page's Booking rules edit)
 * wins over the older `booking_days` / `open_hour` / `close_hour` whenever
 * it is set; the calendar ignores those then.
 */
const BOOKING_KEYS = ['service_periods', 'booking_days', 'open_hour', 'close_hour', 'slot_minutes', 'timezone'] as const;

/** One stretch of the week bookings may start in, as the calendar stores it. */
export interface StoredServicePeriod {
    days: number[];
    first_start: string;
    last_start: string;
}

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

/** Whether *zone* is a real time zone (aliases included) this browser knows. */
function isKnownTimeZone(zone: string): boolean {
    if (!zone || zone === 'Etc/Unknown') return false;
    try {
        new Intl.DateTimeFormat('en', { timeZone: zone });
        return true;
    } catch {
        return false;
    }
}

/** This browser's time zone, else Europe/Dublin (also for "Etc/Unknown"). */
export function browserTimeZone(): string {
    try {
        const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        return isKnownTimeZone(zone) ? zone : DEFAULT_TIMEZONE;
    } catch {
        return DEFAULT_TIMEZONE;
    }
}

/** The time zones to choose from, always including *current*. */
export function timeZoneOptions(current: string): string[] {
    const zones = supportedTimeZones() ?? [DEFAULT_TIMEZONE, 'UTC'];
    return zones.includes(current) ? zones : [current, ...zones];
}

/** Monday to Friday, 9:00–17:00, 30 minutes, in *timezone*. */
function workingWeek(timezone: string): BookingHours {
    return { booking_days: [0, 1, 2, 3, 4], open_hour: 9, close_hour: 17, slot_minutes: 30, timezone };
}

/** Monday to Friday, 9:00–17:00, 30 minutes, in this browser's time zone. */
export function defaultBookingHours(): BookingHours {
    return workingWeek(browserTimeZone());
}

/**
 * Whether a Google Calendar connection's stored settings say anything about
 * its booking hours; one that doesn't books in the calendar's defaults.
 */
export function hasBookingHours(config: Record<string, unknown> | undefined): boolean {
    return !!config && BOOKING_KEYS.some((key) => key in config);
}

function wholeNumber(value: unknown, min: number, max: number): number | null {
    return typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max ? value : null;
}

const CLOCK = /^([01]\d|2[0-3]):([0-5]\d)$/;

/** Minutes after midnight of "17:30", or null. */
function clockMinutes(value: unknown): number | null {
    const match = typeof value === 'string' ? CLOCK.exec(value) : null;
    return match ? Number(match[1]) * 60 + Number(match[2]) : null;
}

/** The calendar's stored service periods, or null when it has none. */
export function storedServicePeriods(config: Record<string, unknown> | undefined): StoredServicePeriod[] | null {
    const periods = config?.service_periods;
    if (!Array.isArray(periods) || periods.length === 0) return null;
    return periods.filter(
        (p): p is StoredServicePeriod =>
            !!p &&
            typeof p === 'object' &&
            Array.isArray((p as StoredServicePeriod).days) &&
            clockMinutes((p as StoredServicePeriod).first_start) !== null &&
            clockMinutes((p as StoredServicePeriod).last_start) !== null,
    );
}

/**
 * The one window of whole hours a single service period stands for, or null
 * when it doesn't fit this dialog's simple hours (several periods, or a
 * start or end off the hour).
 */
function hoursOfPeriods(periods: StoredServicePeriod[], slotMinutes: number) {
    if (periods.length !== 1) return null;
    const [period] = periods;
    const first = clockMinutes(period.first_start);
    const last = clockMinutes(period.last_start);
    if (first === null || last === null || first % 60 !== 0) return null;
    const end = last + slotMinutes;
    if (end % 60 !== 0 || end > 24 * 60 || end <= first) return null;
    const days = period.days.filter((day): day is Weekday => wholeNumber(day, 0, 6) !== null);
    if (days.length === 0) return null;
    return {
        booking_days: [...new Set(days)].sort((a, b) => a - b),
        open_hour: first / 60,
        close_hour: end / 60,
    };
}

/**
 * Whether the calendar books in opening times this dialog can't show as one
 * window (e.g. lunch and dinner, set on the Bookings page). Those are left
 * as they are: the dialog shows them and sends no hours.
 */
export function hasOwnOpeningTimes(config: Record<string, unknown> | undefined): boolean {
    const periods = storedServicePeriods(config);
    if (periods === null) return false;
    const slot = wholeNumber(config?.slot_minutes, 5, 240) ?? 30;
    return hoursOfPeriods(periods, slot) === null;
}

/**
 * The hours a Google Calendar connection already books in, from its stored
 * settings (time zone included). A missing or invalid setting is the
 * calendar's own default, never this browser's time zone, so the agent says
 * what the calendar does.
 */
export function bookingHoursFromConfig(config: Record<string, unknown> | undefined): BookingHours {
    const hours = workingWeek(DEFAULT_TIMEZONE);
    if (!config) return hours;
    hours.slot_minutes = wholeNumber(config.slot_minutes, 5, 240) ?? hours.slot_minutes;
    if (typeof config.timezone === 'string' && config.timezone) hours.timezone = config.timezone;
    const periods = storedServicePeriods(config);
    if (periods !== null) {
        // The calendar books in these, whatever booking_days/open_hour say.
        return { ...hours, ...(hoursOfPeriods(periods, hours.slot_minutes) ?? {}) };
    }
    const days = config.booking_days;
    if (Array.isArray(days)) {
        const valid = days.filter((day): day is Weekday => wholeNumber(day, 0, 6) !== null);
        if (valid.length > 0) hours.booking_days = [...new Set(valid)].sort((a, b) => a - b);
    }
    hours.open_hour = wholeNumber(config.open_hour, 0, 23) ?? hours.open_hour;
    hours.close_hour = wholeNumber(config.close_hour, 1, 24) ?? hours.close_hour;
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
