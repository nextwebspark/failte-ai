"use client";

/**
 * Sample calls shown until a workspace has real ones, so an owner sees how
 * Home, Calls and Follow-ups will look. Everything here lives only in the
 * browser: it is never saved, counted in reports or put in an email. Every
 * screen that shows it says "Sample data" and offers "Hide sample data".
 * As soon as the workspace has a real call, real data replaces it.
 */
import { useCallback, useEffect, useState } from "react";

export type SampleTurn = { role: "agent" | "caller"; text: string };

export type SampleCall = {
    /** Negative, so a sample id can never match a real call. */
    id: number;
    /** When, as minutes before now; screens turn it into a real time. */
    minutesAgo: number;
    callerName: string | null;
    callerNumber: string;
    /** A key of SAMPLE_REASONS. */
    reason: SampleReasonKey;
    summary: string;
    /** Same codes the real calls use (see app/usage/callsView.ts outcomeLabel). */
    outcome: "booking_made" | "question_answered" | "cancelled" | "callback_requested" | "transferred" | "transfer_not_answered" | "hung_up_silent" | "time_was_full";
    durationSeconds: number;
    details: Record<string, string>;
    transcript: SampleTurn[];
    /** Set when the call needs a person. */
    followUp?: "callback" | "transfer_not_answered" | "unanswered_question" | "time_was_full";
    unansweredQuestion?: string;
};

export const SAMPLE_REASONS = {
    reservations: "Reservations",
    questions: "Questions (hours, menu, parking)",
    changes: "Changes & cancellations",
    takeaway: "Takeaway orders",
    other: "Other",
} as const;
export type SampleReasonKey = keyof typeof SAMPLE_REASONS;

const greeting = (business: string): SampleTurn => ({
    role: "agent",
    text: `Hi, thanks for calling ${business}. I'm the AI assistant. How can I help?`,
});

/** The sample calls, worded for the agent's own business name. */
export function sampleCalls(business = "your restaurant"): SampleCall[] {
    const hi = greeting(business);
    return [
        {
            id: -1, minutesAgo: 22, callerName: "Declan Murphy", callerNumber: "+353875511234", reason: "reservations",
            summary: "Booked a table for 4 tonight at 7:00 pm. Asked about parking; one guest is vegetarian.",
            outcome: "booking_made", durationSeconds: 132,
            details: { Name: "Declan Murphy", "Party size": "4 people", "Date and time": "Today, 7:00 pm", Notes: "1 vegetarian" },
            transcript: [hi, { role: "caller", text: "Hi, have you a table for four tonight, around seven?" }, { role: "agent", text: "Yes, 7:00 pm works for four. Can I take a name for the booking?" }, { role: "caller", text: "Murphy. And is there parking near you?" }, { role: "agent", text: "There's a car park two minutes' walk away. You're booked for 7:00 pm tonight, Mr Murphy." }],
        },
        {
            id: -2, minutesAgo: 41, callerName: null, callerNumber: "+353614181234", reason: "questions",
            summary: "Asked if you're open on Sunday. Told 12 to 9 pm.",
            outcome: "question_answered", durationSeconds: 54, details: {},
            transcript: [hi, { role: "caller", text: "Are you open on Sundays?" }, { role: "agent", text: "Yes, on Sunday we're open from 12 to 9 pm." }],
        },
        {
            id: -3, minutesAgo: 54, callerName: "Aoife Walsh", callerNumber: "+353862301234", reason: "changes",
            summary: "Cancelled Friday 6:30 pm for 2.",
            outcome: "cancelled", durationSeconds: 65, details: { Name: "Aoife Walsh", Booking: "Fri 6:30 pm, 2 people" },
            transcript: [hi, { role: "caller", text: "I need to cancel my booking for Friday, half six, under Walsh." }, { role: "agent", text: "That's cancelled for you. Thanks for letting us know." }],
        },
        {
            id: -4, minutesAgo: 63, callerName: null, callerNumber: "+353859021234", reason: "reservations",
            summary: "Wanted 7:30 pm Friday for 5; it was full, offered 8:15 pm. Will ring back to confirm.",
            outcome: "time_was_full", durationSeconds: 160, details: { "Party size": "5 people", "Asked for": "Fri 7:30 pm", Offered: "Fri 8:15 pm" },
            followUp: "time_was_full",
            transcript: [hi, { role: "caller", text: "Could I get a table for five on Friday at half seven?" }, { role: "agent", text: "7:30 is fully booked, but I can offer 8:15 pm. Would that suit?" }, { role: "caller", text: "Let me check with the others and ring back." }],
        },
        {
            id: -5, minutesAgo: 116, callerName: "Conor Ryan", callerNumber: "+353871181234", reason: "other",
            summary: "Asked for the manager; passed to Maria.",
            outcome: "transferred", durationSeconds: 38, details: { Name: "Conor Ryan" },
            transcript: [hi, { role: "caller", text: "Can I speak to the manager please?" }, { role: "agent", text: "Of course, I'll put you through now." }],
        },
        {
            id: -6, minutesAgo: 132, callerName: "Mary Byrne", callerNumber: "+353897741234", reason: "takeaway",
            summary: "Takeaway: 2 margherita, 1 carbonara, collection 6:15 pm.",
            outcome: "question_answered", durationSeconds: 182, details: { Name: "Mary Byrne", Order: "2 margherita, 1 carbonara", Collection: "6:15 pm" },
            transcript: [hi, { role: "caller", text: "I'd like to order a takeaway for collection." }, { role: "agent", text: "Sure, what would you like?" }, { role: "caller", text: "Two margheritas and a carbonara, for quarter past six." }],
        },
        {
            id: -7, minutesAgo: 148, callerName: null, callerNumber: "+353613301234", reason: "reservations",
            summary: "Party of 20 on 14 November; asked for the manager, but the transfer wasn't answered. Agent took their number.",
            outcome: "transfer_not_answered", durationSeconds: 111, details: { "Party size": "20 people", Date: "14 November" },
            followUp: "transfer_not_answered",
            transcript: [hi, { role: "caller", text: "I'm organising a party of twenty for the 14th. Can I talk to someone?" }, { role: "agent", text: "Let me try the manager for you." }, { role: "agent", text: "Sorry, nobody's free right now. Can I take your number so they ring you back?" }],
        },
        {
            id: -8, minutesAgo: 205, callerName: "Sinéad O'Brien", callerNumber: "+353872141234", reason: "changes",
            summary: "Wants to change Saturday 8:00 pm from 6 to 7 people.",
            outcome: "callback_requested", durationSeconds: 108, details: { Name: "Sinéad O'Brien", "Number to call back": "+353 87 214 1234", "Reason for calling": "Change Saturday 8 pm from 6 to 7 people" },
            followUp: "callback",
            transcript: [hi, { role: "caller", text: "I've a booking Saturday at eight for six, can it be seven people?" }, { role: "agent", text: "I can't change the size of that booking myself, so I'll ask the team to ring you back today. Is this the best number?" }, { role: "caller", text: "Yes, this one." }],
        },
        {
            id: -9, minutesAgo: 236, callerName: null, callerNumber: "+353833201234", reason: "questions",
            summary: "Asked if you have gluten-free pasta. Your agent didn't know.",
            outcome: "question_answered", durationSeconds: 47, details: {},
            followUp: "unanswered_question", unansweredQuestion: "Do you have gluten-free pasta?",
            transcript: [hi, { role: "caller", text: "Do you have gluten-free pasta?" }, { role: "agent", text: "I'm not sure about that one. I'll pass the question to the team." }],
        },
        {
            id: -10, minutesAgo: 1290, callerName: "Paul Kennedy", callerNumber: "+353865511234", reason: "reservations",
            summary: "Booked Sunday lunch, 1:00 pm for 6.",
            outcome: "booking_made", durationSeconds: 97, details: { Name: "Paul Kennedy", "Party size": "6 people", "Date and time": "Sun, 1:00 pm" },
            transcript: [hi, { role: "caller", text: "Table for six for Sunday lunch, one o'clock?" }, { role: "agent", text: "You're booked for 1:00 pm on Sunday, Mr Kennedy." }],
        },
        {
            id: -11, minutesAgo: 1303, callerName: null, callerNumber: "+353832201234", reason: "other",
            summary: "Hung up without speaking.",
            outcome: "hung_up_silent", durationSeconds: 4, details: {},
            transcript: [hi],
        },
    ];
}

/** Calls per hour for the sample day, 9am to 9pm, with lunch and dinner peaks. */
export const SAMPLE_CALLS_BY_HOUR: number[] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 6, 7, 3, 2, 3, 6, 7, 4, 1, 1, 0, 0];

const HIDDEN_KEY = "lightmove.sampleData.hidden";
const CHANGED = "lightmove:sample-data";

/**
 * Whether to show sample data: only while the workspace has no real calls
 * (`hasRealCalls` false) and the owner hasn't hidden it. Pass `null` while
 * still loading, and nothing shows. Hiding on one screen hides it on all.
 */
export function useSampleMode(hasRealCalls: boolean | null): { showSample: boolean; hide: () => void; show: () => void } {
    const [hidden, setHidden] = useState(false);

    useEffect(() => {
        const read = () => setHidden(window.localStorage.getItem(HIDDEN_KEY) === "1");
        read();
        window.addEventListener(CHANGED, read);
        window.addEventListener("storage", read);
        return () => {
            window.removeEventListener(CHANGED, read);
            window.removeEventListener("storage", read);
        };
    }, []);

    const set = useCallback((value: boolean) => {
        if (value) window.localStorage.setItem(HIDDEN_KEY, "1");
        else window.localStorage.removeItem(HIDDEN_KEY);
        window.dispatchEvent(new Event(CHANGED));
    }, []);

    return {
        showSample: hasRealCalls === false && !hidden,
        hide: useCallback(() => set(true), [set]),
        show: useCallback(() => set(false), [set]),
    };
}
