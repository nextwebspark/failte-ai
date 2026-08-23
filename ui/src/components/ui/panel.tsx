import { cva, type VariantProps } from "class-variance-authority"
import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * The canvas's inset panel: a recessed `panel-2` surface inside a Card, used for
 * settings groups, callouts and list rows.
 *
 * `accent` adds the 3px left border the canvas uses to mark the primary panel on
 * a screen (sky), a success/live state (brand), or an action-required notice
 * (amber) — see "Model and voice" and "Action required" in the canvas.
 */
const panelVariants = cva("rounded-lg border border-line-soft bg-panel-2", {
    variants: {
        accent: {
            none: "",
            sky: "border-l-[3px] border-l-sky",
            brand: "border-l-[3px] border-l-brand",
            amber: "border-l-[3px] border-l-amber",
            danger: "border-l-[3px] border-l-danger",
        },
        padding: {
            none: "",
            sm: "px-4 py-3.5",
            default: "px-[18px] py-4",
        },
    },
    defaultVariants: {
        accent: "none",
        padding: "default",
    },
})

export interface PanelProps
    extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof panelVariants> { }

function Panel({ className, accent, padding, ...props }: PanelProps) {
    return <div className={cn(panelVariants({ accent, padding }), className)} {...props} />
}

export interface PanelTitleProps extends React.HTMLAttributes<HTMLHeadingElement> {
    /** Heading level, so a panel title keeps its place in the document outline. */
    as?: "h2" | "h3" | "h4" | "div"
}

/** Panel title — 14.5px semibold, per the canvas. */
function PanelTitle({ className, as: Tag = "div", ...props }: PanelTitleProps) {
    return <Tag className={cn("text-[14.5px] font-semibold text-foreground", className)} {...props} />
}

/** Mono sub-caption under a PanelTitle. */
function PanelDescription({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
    return <div className={cn("mt-1 font-mono text-[11.5px] text-ink-3", className)} {...props} />
}

export { Panel, PanelDescription, PanelTitle, panelVariants }
