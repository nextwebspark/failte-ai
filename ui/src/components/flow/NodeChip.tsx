import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/**
 * A small mono chip on a canvas step for what it uses (Conversation.dc.html):
 * sky for tools, the muted panel wash for everything else.
 */
export function NodeChip({
    tone = "mute",
    className,
    ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: "sky" | "mute" }) {
    return (
        <span
            className={cn(
                "inline-block max-w-full truncate rounded-sm px-[7px] py-0.5 font-mono text-[10.5px] font-medium",
                tone === "sky" ? "bg-sky-dim text-sky" : "bg-panel-2 text-ink-3",
                className,
            )}
            {...props}
        />
    );
}
