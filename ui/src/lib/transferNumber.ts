"use client";

import { useEffect, useState } from "react";

import { checkTransferNumberRouteApiV1WorkflowTransferNumberCheckPost } from "@/client/sdk.gen";
import type { TransferNumberCheckResponse, TransferSettings } from "@/client/types.gen";

/** The setup question / business fact that holds "Pass calls to your team". */
export const TRANSFER_NUMBER_KEY = "transfer_number";

export type TransferHint = { tone: "ok" | "error" | "warn"; text: string };

/**
 * The line under the transfer number box, from the server's check:
 * "✓ Irish mobile · saved as +353 87 123 4567", the reason it can't be
 * used, or the demo-number warning. Null while empty or not yet checked.
 */
export function transferHint(check: TransferNumberCheckResponse | null): TransferHint | null {
    if (!check) return null;
    if (!check.ok) return { tone: "error", text: check.error ?? "That number can't be used." };
    if (!check.value) return null;
    if (check.is_demo) return { tone: "warn", text: "Demo number – change it before a live transfer" };
    if (check.is_sip) return { tone: "ok", text: `✓ Phone system address · dialled as typed` };
    return { tone: "ok", text: `✓ ${check.kind} · saved as ${check.display}` };
}

/** What the staff phone shows when the agent passes a call to it. */
export function staffPhoneLine(settings: TransferSettings): string {
    if (settings.staff_phone_shows === "caller") {
        return "Your phone shows the caller's number. If your phone provider refuses it, it shows your agent's number instead.";
    }
    if (settings.staff_phone_shows === "agent") {
        return settings.show_caller_number
            ? "Your phone shows your agent's number. Your phone provider doesn't let us show the caller's."
            : "Your phone shows your agent's number.";
    }
    return "Where your phone provider allows it, your phone shows the caller's number; otherwise it shows your agent's number.";
}

/**
 * Checks the typed number with the server (the same check saving runs),
 * shortly after the owner stops typing. *workflowId* adds the agent's own
 * numbers to what is refused; the Create agent wizard has none yet.
 */
export function useTransferNumberCheck(value: string, workflowId?: number, delayMs = 350) {
    const [checked, setChecked] = useState<{ number: string; check: TransferNumberCheckResponse | null }>({
        number: "",
        check: null,
    });
    const number = value.trim();

    useEffect(() => {
        if (!number) return;
        let cancelled = false;
        const timer = setTimeout(async () => {
            try {
                const res = await checkTransferNumberRouteApiV1WorkflowTransferNumberCheckPost({
                    body: { number, workflow_id: workflowId ?? null },
                });
                if (!cancelled) setChecked({ number, check: res.data ?? null });
            } catch {
                // No hint is better than a wrong one; saving checks again.
                if (!cancelled) setChecked({ number, check: null });
            }
        }, delayMs);
        return () => {
            cancelled = true;
            clearTimeout(timer);
        };
    }, [number, workflowId, delayMs]);

    // A result for an earlier value is never shown against a new one.
    return number && checked.number === number ? checked.check : null;
}
