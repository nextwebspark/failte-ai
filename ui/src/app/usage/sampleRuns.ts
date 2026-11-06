import type { WorkflowRunUsageResponse } from "@/client/types.gen";
import { SAMPLE_REASONS, type SampleCall, sampleCalls } from "@/lib/sampleData";

import {
    BOOKING_OUTCOMES,
    CALLS_TABS,
    type CallsQuery,
    type CallsTab,
    dateRangeFor,
    isPassedToTeam,
    tabUsesDates,
} from "./callsView";

/*
 * Sample mode on Calls: the shared made-up calls (lib/sampleData) shaped like
 * rows from the API, so the same table, cards and panel show them. They live
 * only in the browser; search, tabs and chips filter them here.
 */

/** A row of the list: a real call, or a sample one (negative id, with `sample`). */
export type CallRow = WorkflowRunUsageResponse & { sample?: SampleCall };

export function isSampleRun(run: { id: number }): boolean {
    return run.id < 0;
}

const BOOKING_OUTCOME: Partial<Record<SampleCall["outcome"], string>> = {
    booking_made: "booked",
    cancelled: "cancelled",
};

function sampleRun(call: SampleCall, now: Date): CallRow {
    const transferred = call.outcome === "transferred";
    return {
        id: call.id,
        workflow_id: 0,
        workflow_name: null,
        name: "Sample call",
        created_at: new Date(now.getTime() - call.minutesAgo * 60_000).toISOString(),
        dograh_token_usage: 0,
        call_duration_seconds: call.durationSeconds,
        caller_number: call.callerNumber,
        called_number: null,
        call_type: "inbound",
        mode: "twilio",
        disposition: call.outcome,
        gathered_context: {
            extracted_variables: { ...call.details },
            ...(call.callerName && { caller_name: call.callerName }),
            ...(transferred && { call_status: "transfer_call" }),
            ...(BOOKING_OUTCOME[call.outcome] && { booking_outcome: BOOKING_OUTCOME[call.outcome] }),
            mapped_call_disposition: call.outcome,
        },
        is_completed: true,
        summary: call.summary,
        reason_label: SAMPLE_REASONS[call.reason],
        unanswered_questions: call.unansweredQuestion ? [call.unansweredQuestion] : [],
        sample: call,
    };
}

/** The sample calls as list rows, newest first, worded for the business. */
export function sampleRuns(businessName: string | undefined, now: Date): CallRow[] {
    return sampleCalls(businessName)
        .map((call) => sampleRun(call, now))
        .sort((a, b) => b.created_at.localeCompare(a.created_at));
}

/** The same digits rule as the server's search (api/db/filters.py search_digits). */
export function searchDigits(text: string): string {
    const digits = text.replace(/\D/g, "");
    return digits.startsWith("00") ? digits.slice(2) : digits.replace(/^0+/, "");
}

function matchesSearch(run: CallRow, q: string): boolean {
    const needle = q.trim().toLowerCase();
    if (!needle) return true;
    const call = run.sample;
    const texts = [
        call?.callerName ?? "",
        run.summary ?? "",
        ...(call?.transcript.map((turn) => turn.text) ?? []),
    ];
    if (texts.some((value) => value.toLowerCase().includes(needle))) return true;
    const digits = searchDigits(q);
    return digits.length > 0 && (run.caller_number ?? "").includes(digits);
}

function onTab(run: CallRow, tab: CallsTab): boolean {
    switch (tab) {
        case "follow_up":
            return Boolean(run.sample?.followUp);
        case "bookings":
            return BOOKING_OUTCOMES.includes(String(run.gathered_context?.booking_outcome ?? ""));
        case "team":
            return isPassedToTeam(run.gathered_context);
        default:
            return true;
    }
}

/** The sample rows the controls leave, as the API would filter real ones. */
export function filterSampleRuns(runs: CallRow[], query: CallsQuery, tab: CallsTab, now: Date): CallRow[] {
    const range = tabUsesDates(tab) ? dateRangeFor(query, now) : null;
    return runs.filter((run) => {
        if (!onTab(run, tab)) return false;
        if (range) {
            const at = new Date(run.created_at);
            if (at < range.from || at > range.to) return false;
        }
        if (query.outcome && run.disposition !== query.outcome) return false;
        if (query.who === "team" && !isPassedToTeam(run.gathered_context)) return false;
        if (query.who === "agent" && isPassedToTeam(run.gathered_context)) return false;
        return matchesSearch(run, query.q);
    });
}

/** Each tab's total for the sample, with the same search and chips. */
export function sampleTabCounts(runs: CallRow[], query: CallsQuery, now: Date): Record<CallsTab, number> {
    return Object.fromEntries(
        CALLS_TABS.map(({ value }) => [value, filterSampleRuns(runs, query, value, now).length]),
    ) as Record<CallsTab, number>;
}

/** The outcomes the sample uses, for the Outcome chip. */
export function sampleOutcomeCodes(runs: CallRow[]): string[] {
    return [...new Set(runs.map((run) => run.disposition).filter((code): code is string => Boolean(code)))];
}
