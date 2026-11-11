import type { CallResult } from "@/client/types.gen";
import { type ChipTone, RESULT_WORDS } from "@/components/dashboard/dashboardView";
import type { StatusTone } from "@/components/ui/status-pill";

import { callOutcome as storedOutcome } from "./callsView";

/** The stored-code fallback's tones in Home's chip colours. */
const CHIP_TONE: Record<StatusTone, ChipTone> = {
    ok: "brand",
    info: "sky",
    warn: "amber",
    bad: "danger",
    live: "sky",
    mute: "neutral",
};

/**
 * How a call went, in the words and colours Home and Follow-ups use. The API
 * reads every call with one rule (``api/services/dashboard/calls.py``
 * ``call_result``) and sends it as ``result``; this only puts it into words,
 * so one call reads the same on every screen ("Booking made", not the
 * engine's "Call finished"). A response without ``result`` falls back to the
 * stored ending code.
 */
export function callResultChip(
    run: {
        result?: CallResult | null;
        disposition?: string | null;
        gathered_context?: Record<string, unknown> | null;
        is_completed?: boolean | null;
        created_at?: string;
    },
    now: number = Date.now(),
): { label: string; tone: ChipTone } {
    if (run.result && run.result in RESULT_WORDS) return RESULT_WORDS[run.result];
    const stored = storedOutcome(run, now);
    return { label: stored.label, tone: CHIP_TONE[stored.tone] };
}
