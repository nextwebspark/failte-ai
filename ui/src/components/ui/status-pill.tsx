import { cva, type VariantProps } from "class-variance-authority"
import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * The canvas status pill (`pill()` in app-doc/claude-design/Failte AI v2.dc.html):
 * uppercase mono on a dim wash of its accent.
 *
 * Five tones cover every status the app shows, so screens pick a tone instead of
 * inventing a colour. Prefer this over a per-screen status→colour map.
 */
const statusPillVariants = cva(
    "inline-flex items-center whitespace-nowrap rounded-sm px-2.5 py-[3px] font-mono text-[10.5px] font-semibold uppercase tracking-[0.04em]",
    {
        variants: {
            tone: {
                ok: "bg-ok-dim text-ok",
                info: "bg-sky-dim text-sky",
                warn: "bg-amber-dim text-amber",
                bad: "bg-danger-dim text-danger",
                mute: "bg-panel text-ink-3",
            },
        },
        defaultVariants: {
            tone: "mute",
        },
    }
)

export type StatusTone = NonNullable<VariantProps<typeof statusPillVariants>["tone"]>

export interface StatusPillProps
    extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof statusPillVariants> {
    /** Renders a filled dot before the label, as the canvas draft/live badges do. */
    dot?: boolean
}

function StatusPill({ className, tone, dot = false, children, ...props }: StatusPillProps) {
    return (
        <span className={cn(statusPillVariants({ tone }), dot && "gap-1.5", className)} {...props}>
            {dot ? <span className="size-1.5 rounded-full bg-current" aria-hidden /> : null}
            {children}
        </span>
    )
}

/**
 * Shared status -> tone map. Workflow versions, tools and anything else with a
 * draft/published/active/archived lifecycle should read from here rather than
 * restating the colours locally.
 */
const STATUS_TONE: Record<string, StatusTone> = {
    draft: "warn",
    published: "ok",
    active: "ok",
    archived: "mute",
    inactive: "mute",
    failed: "bad",
}

/** Tone for a lifecycle status string, defaulting to the neutral chip. */
function statusTone(status: string): StatusTone {
    return STATUS_TONE[status] ?? "mute"
}

export { STATUS_TONE, StatusPill, statusPillVariants, statusTone }
