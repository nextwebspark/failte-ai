import * as React from "react"

import { Panel, type PanelProps } from "@/components/ui/panel"
import { cn } from "@/lib/utils"

export interface StatTileProps extends Omit<PanelProps, "children" | "title"> {
    /** Uppercase mono caption above the figure. */
    label: React.ReactNode
    /** The figure itself. */
    value: React.ReactNode
    /** Optional mono sub-line — a delta, a period, a qualifier. */
    detail?: React.ReactNode
}

/**
 * The canvas overview tile: uppercase mono label, large figure, mono detail line,
 * on an accented panel.
 */
function StatTile({ className, label, value, detail, accent = "sky", ...props }: StatTileProps) {
    return (
        <Panel accent={accent} padding="sm" className={cn("px-4", className)} {...props}>
            <div className="font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-3">
                {label}
            </div>
            <div className="mt-1.5 text-2xl font-bold text-foreground">{value}</div>
            {detail ? (
                <div className="mt-0.5 font-mono text-[11.5px] text-ink-3">{detail}</div>
            ) : null}
        </Panel>
    )
}

export { StatTile }
