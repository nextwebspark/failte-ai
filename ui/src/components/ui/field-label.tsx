import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * The canvas's micro form label: uppercase mono, 10.5px, wide tracking, muted.
 * Used above every select, input and control group in the agent editor.
 *
 * Renders a real <label>, so pair it with the control's id via htmlFor.
 */
function FieldLabel({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
    return (
        <label
            className={cn(
                "mb-1.5 block font-mono text-[10.5px] font-semibold uppercase tracking-[0.04em] text-ink-3",
                className
            )}
            {...props}
        />
    )
}

export { FieldLabel }
