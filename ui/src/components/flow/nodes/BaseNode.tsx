import { forwardRef, HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export const BaseNode = forwardRef<
    HTMLDivElement,
    HTMLAttributes<HTMLDivElement> & {
        selected?: boolean;
        invalid?: boolean;
        selected_through_edge?: boolean;
        hovered_through_edge?: boolean;
        runtimeActive?: boolean;
    }
>(({ children, className, selected, invalid, selected_through_edge, hovered_through_edge, runtimeActive, ...props }, ref) => (
    <div
        ref={ref}
        className={cn(
            "relative w-[288px] rounded-lg border border-line bg-panel text-card-foreground",
            className,
            // Hover would otherwise beat every state border below (a :hover rule
            // outranks a plain class), so only resting steps get it.
            !selected && !invalid && !runtimeActive && !selected_through_edge && !hovered_through_edge &&
                "hover:border-ink-3/50",
            // Later states win: an invalid step stays red even when selected,
            // and the live call's step is the one thing that glows orange.
            selected && "border-brand ring-4 ring-brand-dim",
            hovered_through_edge && "ring-2 ring-brand/50",
            !hovered_through_edge && selected_through_edge && "ring-1 ring-brand/40",
            invalid && "border-danger",
            runtimeActive && "border-live ring-4 ring-live-dim",
        )}
        tabIndex={0}
        {...props}
    >
        {children}
    </div>
));

BaseNode.displayName = "BaseNode";
