"use client";

import { Panel, useReactFlow, useViewport } from "@xyflow/react";
import { LayoutGrid, Maximize, Minus, Plus, Redo2, Undo2 } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

interface CanvasToolbarProps {
    /** Viewing an old version: only the view controls apply. */
    readOnly: boolean;
    onAddNode: () => void;
    onTidy: () => void;
    onUndo: () => void;
    onRedo: () => void;
    canUndo: boolean;
    canRedo: boolean;
}

function ToolButton({
    label,
    shortcut,
    onClick,
    disabled,
    children,
}: {
    label: string;
    shortcut?: string;
    onClick: () => void;
    disabled?: boolean;
    children: ReactNode;
}) {
    return (
        <Tooltip>
            <TooltipTrigger asChild>
                <Button
                    variant="ghost"
                    size="icon"
                    aria-label={label}
                    onClick={onClick}
                    disabled={disabled}
                    className="size-[34px] text-ink-2 hover:bg-panel-2 hover:text-foreground"
                >
                    {children}
                </Button>
            </TooltipTrigger>
            <TooltipContent side="top">
                {label}
                {shortcut && <span className="ml-1.5 font-mono text-[11px] opacity-70">{shortcut}</span>}
            </TooltipContent>
        </Tooltip>
    );
}

const Divider = () => <span aria-hidden className="mx-1 h-[22px] w-px bg-line-soft" />;

/**
 * The canvas's one floating toolbar, bottom centre (Conversation.dc.html):
 * add a step, then the view (zoom, fit, tidy), then undo and redo. Rendered
 * inside <ReactFlow> so it can read and drive the viewport.
 */
export function CanvasToolbar({ readOnly, onAddNode, onTidy, onUndo, onRedo, canUndo, canRedo }: CanvasToolbarProps) {
    const { zoomIn, zoomOut, fitView } = useReactFlow();
    const { zoom } = useViewport();
    const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
    const mod = isMac ? "⌘" : "Ctrl+";

    return (
        <Panel position="bottom-center" className="!mb-4">
            <TooltipProvider delayDuration={300}>
                <div
                    role="toolbar"
                    aria-label="Canvas"
                    className="flex items-center gap-1 rounded-xl border border-line bg-panel p-1.5 shadow-[var(--panel-shadow)]"
                >
                    {!readOnly && (
                        <>
                            <Button
                                size="sm"
                                onClick={onAddNode}
                                aria-label="Add step"
                                className="h-[34px] px-2.5 sm:px-3.5"
                            >
                                <Plus className="h-3.5 w-3.5" />
                                <span className="hidden sm:inline">Add step</span>
                            </Button>
                            <Divider />
                        </>
                    )}
                    <ToolButton label="Zoom out" onClick={() => void zoomOut({ duration: 150 })}>
                        <Minus className="h-4 w-4" />
                    </ToolButton>
                    <span
                        className="hidden min-w-[44px] text-center font-mono text-xs text-ink-2 tabular-nums sm:inline"
                        aria-label={`Zoom ${Math.round(zoom * 100)} percent`}
                    >
                        {Math.round(zoom * 100)}%
                    </span>
                    <ToolButton label="Zoom in" onClick={() => void zoomIn({ duration: 150 })}>
                        <Plus className="h-4 w-4" />
                    </ToolButton>
                    <ToolButton label="Fit to view" onClick={() => void fitView({ padding: 0.2, duration: 200 })}>
                        <Maximize className="h-4 w-4" />
                    </ToolButton>
                    {!readOnly && (
                        <>
                            <ToolButton label="Tidy layout" onClick={onTidy}>
                                <LayoutGrid className="h-4 w-4" />
                            </ToolButton>
                            <Divider />
                            <ToolButton label="Undo" shortcut={`${mod}Z`} onClick={onUndo} disabled={!canUndo}>
                                <Undo2 className="h-4 w-4" />
                            </ToolButton>
                            <ToolButton label="Redo" shortcut={`${mod}⇧Z`} onClick={onRedo} disabled={!canRedo}>
                                <Redo2 className="h-4 w-4" />
                            </ToolButton>
                        </>
                    )}
                </div>
            </TooltipProvider>
        </Panel>
    );
}
