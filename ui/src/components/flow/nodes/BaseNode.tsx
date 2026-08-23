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
            // Base styling - larger with max width, uses semantic colors
            "relative rounded-lg border bg-card text-card-foreground min-w-[320px] max-w-[400px] min-h-[120px]",
            // Border styling
            "border-line",
            className,
            // Selected state - prominent halo effect. Sky, not primary: the
            // canvas reserves the brand green for actions and marks selection blue.
            selected ? "border-sky ring-2 ring-sky/40" : "",
            // Invalid state
            invalid ? "border-destructive ring-1 ring-destructive/30" : "",
            // Hovered through edge takes precedence over selected through edge
            hovered_through_edge ? "ring-2 ring-sky/60" : "",
            !hovered_through_edge && selected_through_edge ? "ring-1 ring-sky/50" : "",
            runtimeActive ? "ring-2 ring-sky/60 shadow-panel" : "",
            !selected_through_edge && !hovered_through_edge && "hover:border-ink-3/50",
        )}
        tabIndex={0}
        {...props}
    >
        {children}
    </div>
));

BaseNode.displayName = "BaseNode";
