import * as React from "react"

import { cn } from "@/lib/utils"

export interface SectionHeadingProps extends React.HTMLAttributes<HTMLDivElement> {
    /** Trailing slot: the canvas puts a mono hint, a link or a small button here. */
    action?: React.ReactNode
    /** Heading level for the title. Defaults to h2. */
    as?: "h1" | "h2" | "h3"
}

/**
 * Title, hairline rule, optional trailing slot — the section divider used
 * throughout the design canvas. The rule absorbs the free space, so the action
 * always sits flush right regardless of title length.
 */
function SectionHeading({
    className,
    children,
    action,
    as: Tag = "h2",
    ...props
}: SectionHeadingProps) {
    return (
        <div className={cn("mb-3 flex items-center gap-3.5", className)} {...props}>
            <Tag className="whitespace-nowrap text-base font-bold text-foreground">{children}</Tag>
            <span className="h-px flex-1 bg-line-soft" aria-hidden />
            {action ? <div className="flex flex-none items-center gap-2">{action}</div> : null}
        </div>
    )
}

/** Mono caption sized to sit in a SectionHeading's action slot. */
function SectionHint({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) {
    return <span className={cn("font-mono text-[11.5px] text-ink-3", className)} {...props} />
}

export { SectionHeading, SectionHint }
