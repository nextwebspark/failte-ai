import { Position } from "@xyflow/react";
import { AlertCircle } from "lucide-react";
import { ReactNode } from "react";

import { BaseHandle } from "@/components/flow/nodes/BaseHandle";
import { BaseNode } from "@/components/flow/nodes/BaseNode";
import { StatusPill } from "@/components/ui/status-pill";
import { cn } from "@/lib/utils";

/**
 * The colour of a step's icon tile. It matches the canvas legend: brand when
 * the agent speaks, sky when the step uses a tool; amber, danger and mute mark
 * global instructions, the end of the call and steps outside the call.
 */
export type NodeTone = "brand" | "sky" | "amber" | "danger" | "mute";

const ICON_TILE: Record<NodeTone, string> = {
    brand: "bg-brand-dim text-brand",
    sky: "bg-sky-dim text-sky",
    amber: "bg-amber-dim text-amber",
    danger: "bg-danger-dim text-danger",
    mute: "bg-panel-2 text-ink-2",
};

interface NodeContentProps {
    selected: boolean;
    invalid?: boolean;
    /** Why the step is invalid, shown on the card. */
    invalidMessage?: string | null;
    selected_through_edge?: boolean;
    hovered_through_edge?: boolean;
    runtimeActive?: boolean;
    title: string;
    icon: ReactNode;
    tone: NodeTone;
    /** Short kind label at the right of the header, e.g. "Agent". */
    kindLabel: string;
    /** The call starts here: a brand bar down the header's left edge. */
    isStart?: boolean;
    hasSourceHandle?: boolean;
    hasTargetHandle?: boolean;
    children?: ReactNode;
    className?: string;
    onDoubleClick?: () => void;
}

/** One step on the canvas (Conversation.dc.html): icon, name and kind, then a preview. */
export const NodeContent = ({
    selected,
    invalid,
    invalidMessage,
    selected_through_edge,
    hovered_through_edge,
    runtimeActive,
    title,
    icon,
    tone,
    kindLabel,
    isStart = false,
    hasSourceHandle = false,
    hasTargetHandle = false,
    children,
    className = "",
    onDoubleClick,
}: NodeContentProps) => {
    return (
        <BaseNode
            selected={selected}
            invalid={invalid}
            selected_through_edge={selected_through_edge}
            hovered_through_edge={hovered_through_edge}
            runtimeActive={runtimeActive}
            className={cn("p-0", className)}
            onDoubleClick={onDoubleClick}
        >
            {hasTargetHandle && <BaseHandle type="target" position={Position.Top} />}

            <header
                className={cn(
                    "flex items-center gap-2 border-b border-line-soft px-3 py-2.5",
                    isStart && "rounded-tl-lg border-l-[3px] border-l-brand",
                )}
            >
                <span
                    aria-hidden
                    className={cn(
                        "grid size-[22px] shrink-0 place-items-center rounded-sm [&>svg]:size-3",
                        ICON_TILE[tone],
                    )}
                >
                    {icon}
                </span>
                <h3 className="min-w-0 flex-1 truncate text-[13px] font-semibold text-foreground" title={title}>
                    {title}
                </h3>
                {runtimeActive ? (
                    <StatusPill tone="live" dot className="px-1.5 py-0.5 text-[10px]">
                        On
                    </StatusPill>
                ) : invalid ? (
                    <span className="inline-flex shrink-0 items-center gap-1 font-mono text-[10px] font-semibold tracking-[0.04em] text-danger uppercase">
                        <AlertCircle className="size-[11px]" aria-hidden />
                        Needs a fix
                    </span>
                ) : (
                    <span className="shrink-0 font-mono text-[10px] font-medium tracking-[0.04em] text-ink-3 uppercase">
                        {kindLabel}
                    </span>
                )}
            </header>

            <div className="px-3 py-2.5">
                {invalid && invalidMessage && (
                    <p className="mb-1.5 text-xs text-danger">{invalidMessage}</p>
                )}
                {children}
            </div>

            {hasSourceHandle && <BaseHandle type="source" position={Position.Bottom} />}
        </BaseNode>
    );
};
