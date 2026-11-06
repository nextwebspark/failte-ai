/**
 * The shared sample calls (lib/sampleData.ts) in the shapes Home and
 * Follow-ups draw. Only the call figures are made up: the agent's status,
 * number and credit stay real.
 */
import type { CallResult, DashboardSummaryResponse, FollowUpItem } from "@/client/types.gen";
import {
    SAMPLE_CALLERS_WANTED,
    SAMPLE_CALLS_BY_HOUR,
    SAMPLE_TILES,
    type SampleCall,
    sampleCalls,
    sampleCallTime,
    sampleFollowUpCalls,
} from "@/lib/sampleData";

import type { ChipTone } from "./dashboardView";

const RESULT: Record<SampleCall["outcome"], CallResult> = {
    booking_made: "booking_made",
    question_answered: "handled",
    cancelled: "handled",
    callback_requested: "callback_requested",
    transferred: "passed_to_team",
    transfer_not_answered: "transfer_not_answered",
    hung_up_silent: "hung_up_silent",
    time_was_full: "handled",
};

/** The sample outcomes real calls don't have a chip for (see RESULT_WORDS). */
export const SAMPLE_OUTCOME_WORDS: Partial<Record<SampleCall["outcome"], { label: string; tone: ChipTone }>> = {
    question_answered: { label: "Question answered", tone: "neutral" },
    cancelled: { label: "Cancelled", tone: "sky" },
    time_was_full: { label: "Follow up", tone: "amber" },
};

/** Home with the sample day's calls in place of the (empty) real ones. */
export function sampleSummary(real: DashboardSummaryResponse, business: string | undefined, now: Date): DashboardSummaryResponse {
    const calls = sampleCalls(business);
    return {
        ...real,
        range: "today",
        tiles: { ...SAMPLE_TILES },
        previous_calls: SAMPLE_TILES.calls - 8,
        calls_change: 8,
        calls_by_hour: [...SAMPLE_CALLS_BY_HOUR],
        recent_calls: calls.slice(0, 5).map((call) => ({
            run_id: call.id,
            workflow_id: real.agents[0]?.id ?? 0,
            created_at: sampleCallTime(call, now),
            caller_number: call.callerNumber,
            caller_name: call.callerName,
            result: RESULT[call.outcome],
            duration_seconds: call.durationSeconds,
            has_recording: true,
            summary: call.summary,
            reason_label: null,
        })),
        callers_wanted: SAMPLE_CALLERS_WANTED.map((r) => ({ ...r })),
        wording: { template: "restaurant", bookings_label: "bookings taken" },
    };
}

/** The sample calls' outcome by id, for their chips. */
export function sampleOutcomes(business?: string): Map<number, SampleCall["outcome"]> {
    return new Map(sampleCalls(business).map((call) => [call.id, call.outcome]));
}

/** The sample follow-ups, as the follow-ups list returns them. */
export function sampleFollowUpItems(business: string | undefined, now: Date): FollowUpItem[] {
    return sampleFollowUpCalls(business).map((call) => {
        const kind = call.followUp ?? "callback";
        return {
            run_id: call.id,
            workflow_id: 0,
            workflow_name: business ?? "",
            kind,
            created_at: sampleCallTime(call, now),
            caller_number: call.callerNumber,
            caller_name: call.callerName,
            callback_number: null,
            call_reason: kind === "callback" || kind === "transfer_not_answered" ? call.summary : null,
            duration_seconds: call.durationSeconds,
            has_recording: true,
            repeat_count: null,
            first_call_at: null,
            done_at: null,
            done_by: null,
            summary: call.summary,
            questions: call.unansweredQuestion ? [call.unansweredQuestion] : [],
        };
    });
}
