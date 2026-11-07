"use client";

import type { TransferHint } from "@/lib/transferNumber";
import { cn } from "@/lib/utils";

/** The live line under a transfer number box (see `transferHint`). */
export function TransferNumberHint({ hint, id }: { hint: TransferHint | null; id?: string }) {
    if (!hint) return null;
    return (
        <p
            id={id}
            role={hint.tone === "error" ? "alert" : "status"}
            className={cn(
                "mt-1 text-[12.5px] font-medium",
                hint.tone === "ok" && "text-brand",
                hint.tone === "error" && "text-danger",
                hint.tone === "warn" && "text-amber",
            )}
        >
            {hint.tone === "error" && <span aria-hidden>✕ </span>}
            {hint.text}
        </p>
    );
}
