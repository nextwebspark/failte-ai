import { cva, type VariantProps } from "class-variance-authority"
import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * The canvas's rounded mono tag. Distinct from StatusPill: chips are inline
 * references (template variables, captured fields, attached tools), not statuses.
 *
 * `outline` is the neutral form and `dashed` the "+ Add" affordance.
 */
const chipVariants = cva(
    "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 font-mono text-[11.5px] font-medium",
    {
        variants: {
            tone: {
                sky: "bg-sky-dim text-sky",
                ok: "bg-ok-dim text-ok",
                brand: "bg-brand-dim text-brand",
                amber: "bg-amber-dim text-amber",
                outline: "border border-line bg-panel text-ink-3",
                dashed: "border border-dashed border-line bg-transparent text-ink-3 transition-colors hover:border-sky hover:text-sky",
            },
        },
        defaultVariants: {
            tone: "outline",
        },
    }
)

export interface ChipProps
    extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof chipVariants> { }

function Chip({ className, tone, ...props }: ChipProps) {
    return <span className={cn(chipVariants({ tone }), className)} {...props} />
}

export { Chip, chipVariants }
