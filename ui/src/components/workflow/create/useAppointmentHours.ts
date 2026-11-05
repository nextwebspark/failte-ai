'use client';

import { useCallback, useEffect, useState } from 'react';

import type { DuplicateTemplateRequest, TemplateSetupField, WorkflowTemplateResponse } from '@/client/types.gen';
import {
    type BookingHours,
    bookingHoursFromConfig,
    bookingHoursProblem,
    defaultBookingHours,
    isAppointmentHoursField,
} from '@/lib/appointmentHours';

import type { IntegrationConnect } from './useIntegrationConnect';

/**
 * Whose booking hours these are, which the user should know before changing
 * them: a calendar connected just now, one other agents already book with,
 * or one this user's role can't change.
 */
export type HoursTarget = 'new_calendar' | 'shared_calendar' | 'read_only';

export interface AppointmentHours {
    /** The template's hours question; only asked when the agent books into a calendar. */
    field: TemplateSetupField | null;
    hours: BookingHours;
    edit: (hours: BookingHours) => void;
    target: HoursTarget;
    problem: string | null;
    /** The hours' part of the create request. */
    request: Pick<DuplicateTemplateRequest, 'appointment_hours' | 'apply_to_calendar'>;
}

/**
 * The appointment hours of an agent that books with *calendar*. A calendar
 * connected in this dialog's sign-in pop-up starts from the defaults (in this
 * browser's time zone) and gets these hours. Any other calendar, including
 * one just connected on the Integrations page, shows the hours it already
 * books in, and only changes them when the user edits them, since every
 * agent booking with it shares them.
 */
export function useAppointmentHours(
    template: WorkflowTemplateResponse | null,
    calendar: IntegrationConnect,
    attached: boolean,
    canChangeCalendar: boolean,
): AppointmentHours {
    const [hours, setHours] = useState<BookingHours>(defaultBookingHours);
    const [edited, setEdited] = useState(false);

    const templateField = template?.setup_fields?.find(isAppointmentHoursField) ?? null;
    const field = attached ? templateField : null;
    const fresh = calendar.connectedHere;
    const config = attached ? calendar.connection?.config : undefined;

    // A new template starts over.
    useEffect(() => {
        setHours(defaultBookingHours());
        setEdited(false);
    }, [template?.id]);

    // Until the user edits them, the hours follow the calendar.
    useEffect(() => {
        if (!config || edited) return;
        setHours(fresh ? defaultBookingHours() : bookingHoursFromConfig(config));
    }, [config, fresh, edited]);

    const edit = useCallback((next: BookingHours) => {
        setHours(next);
        setEdited(true);
    }, []);

    const target: HoursTarget = fresh ? 'new_calendar' : canChangeCalendar ? 'shared_calendar' : 'read_only';
    return {
        field,
        hours,
        edit,
        target,
        problem: field ? bookingHoursProblem(hours) : null,
        request: field ? { appointment_hours: hours, apply_to_calendar: fresh || edited } : {},
    };
}
