"use client";

import { Panel } from "@xyflow/react";

const ITEMS = [
    { label: "Agent speaks", swatch: "bg-brand" },
    { label: "Uses a tool", swatch: "bg-sky" },
    { label: "Where the live call is", swatch: "bg-live" },
] as const;

/**
 * What the step colours mean (Conversation.dc.html), top right of the canvas.
 * Hidden on small screens, where it would cover the steps.
 */
export function CanvasLegend() {
    return (
        <Panel position="top-right" className="!m-4 hidden md:block">
            <div className="flex w-[180px] flex-col gap-1.5 rounded-lg border border-line bg-panel px-3 py-2.5 shadow-panel">
                <span id="canvas-legend-title" className="text-[10.5px] font-semibold tracking-[0.08em] text-ink-3 uppercase">
                    Legend
                </span>
                <ul aria-labelledby="canvas-legend-title" className="flex flex-col gap-1.5">
                    {ITEMS.map(({ label, swatch }) => (
                        <li key={label} className="flex items-center gap-2 text-xs text-ink-2">
                            {/* 2px: the 6px scale step would turn a 10px swatch into a dot. */}
                            <span aria-hidden className={`size-2.5 shrink-0 rounded-xs ${swatch}`} />
                            {label}
                        </li>
                    ))}
                </ul>
            </div>
        </Panel>
    );
}
