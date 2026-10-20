import { BaseEdge, type Edge, EdgeLabelRenderer, type EdgeProps, getSmoothStepPath, useReactFlow } from '@xyflow/react';
import { AlertCircle, Pencil, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { useWorkflow, useWorkflowOptional } from "@/app/workflow/[workflowId]/contexts/WorkflowContext";
import { useWorkflowStore } from "@/app/workflow/[workflowId]/stores/workflowStore";
import { StaticTextWarning, TextOrAudioInput } from "@/components/flow/TextOrAudioInput";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from '@/components/ui/textarea';
import { cn } from "@/lib/utils";

import { FlowEdge, FlowEdgeData, FlowNode } from '../types';
type CustomEdge = Edge<{ value: number }, 'custom'>;


interface EdgeDetailsDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    data?: FlowEdgeData;
    onSave: (value: FlowEdgeData) => void;
}

const EdgeDetailsDialog = ({ open, onOpenChange, data, onSave }: EdgeDetailsDialogProps) => {
    const readOnly = useWorkflowOptional()?.readOnly ?? false;
    const { recordings } = useWorkflow();
    const [condition, setCondition] = useState(data?.condition ?? '');
    const [label, setLabel] = useState(data?.label ?? '');
    const [transitionSpeech, setTransitionSpeech] = useState(data?.transition_speech ?? '');
    const [transitionSpeechType, setTransitionSpeechType] = useState<'text' | 'audio'>(data?.transition_speech_type ?? 'text');
    const [transitionSpeechRecordingId, setTransitionSpeechRecordingId] = useState(data?.transition_speech_recording_id ?? '');

    // Update form state when data changes (e.g., from undo/redo)
    useEffect(() => {
        if (open) {
            setCondition(data?.condition ?? '');
            setLabel(data?.label ?? '');
            setTransitionSpeech(data?.transition_speech ?? '');
            setTransitionSpeechType(data?.transition_speech_type ?? 'text');
            setTransitionSpeechRecordingId(data?.transition_speech_recording_id ?? '');
        }
    }, [data, open]);

    const handleSave = useCallback(() => {
        onSave({
            condition,
            label,
            transition_speech: transitionSpeechType === 'text' ? (transitionSpeech || undefined) : undefined,
            transition_speech_type: transitionSpeechType,
            transition_speech_recording_id: transitionSpeechType === 'audio' ? (transitionSpeechRecordingId || undefined) : undefined,
        });
        onOpenChange(false);
    }, [condition, label, transitionSpeech, transitionSpeechType, transitionSpeechRecordingId, onSave, onOpenChange]);

    // Handle Cmd+S / Ctrl+S keyboard shortcut to save
    useEffect(() => {
        if (!open || readOnly) return;

        const handleKeyDown = (e: KeyboardEvent) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 's') {
                e.preventDefault();
                e.stopImmediatePropagation();
                handleSave();
            }
        };

        window.addEventListener('keydown', handleKeyDown, true);
        return () => window.removeEventListener('keydown', handleKeyDown, true);
    }, [open, readOnly, handleSave]);

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-h-[85vh] flex flex-col">
                <DialogHeader>
                    <DialogTitle>Edit Condition</DialogTitle>
                    {data?.invalid && data.validationMessage && (
                        <div className="mt-2 flex items-center gap-2 rounded-md border border-danger/30 bg-danger-dim p-2 text-sm text-danger">
                            <AlertCircle className="h-4 w-4" />
                            <span>{data.validationMessage}</span>
                        </div>
                    )}
                </DialogHeader>
                <div className="grid gap-4 py-4 overflow-y-auto">
                    <div className="grid gap-2">
                        <Label>Condition Label</Label>
                        <Label className="text-xs text-muted-foreground">
                            Enter a short label which helps identify this pathway in logs
                        </Label>
                        <Input
                            type="text"
                            value={label}
                            maxLength={64}
                            onChange={(e) => setLabel(e.target.value)}
                        />
                        <div className="text-xs text-muted-foreground">
                            {label.length}/64 characters
                        </div>
                    </div>
                    <div className="grid gap-2">
                        <Label>Condition</Label>
                        <Label className="text-xs text-muted-foreground">
                            Describe a condition that will be evaluated to determine if this pathway should be taken
                        </Label>
                        <Textarea
                            value={condition}
                            onChange={(e) => setCondition(e.target.value)}
                        />
                    </div>
                    <div className="grid gap-2">
                        <Label>Transition Speech</Label>
                        <Label className="text-xs text-muted-foreground">
                            Optional text or audio the assistant will play right before transitioning to the node.
                            This will not be attached in Conversation Context. Use this as simple filler to reduce latency.
                        </Label>
                        <TextOrAudioInput
                            type={transitionSpeechType}
                            onTypeChange={setTransitionSpeechType}
                            recordingId={transitionSpeechRecordingId}
                            onRecordingIdChange={setTransitionSpeechRecordingId}
                            recordings={recordings ?? []}
                        >
                            <>
                                <StaticTextWarning />
                                <Textarea
                                    value={transitionSpeech}
                                    placeholder="e.g. Let me transfer you to our billing department..."
                                    onChange={(e) => setTransitionSpeech(e.target.value)}
                                />
                            </>
                        </TextOrAudioInput>
                    </div>
                </div>
                <DialogFooter>
                    <div className="flex items-center gap-2">
                        <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
                        <Button onClick={handleSave} disabled={readOnly}>
                            {readOnly ? "Read Only" : "Save"}
                        </Button>
                    </div>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};

interface CustomEdgeProps extends EdgeProps {
    data: FlowEdgeData;
}

export default function CustomEdge(props: CustomEdgeProps) {
    const { id, source, target, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, style, selected } = props;

    const { getEdges, setNodes } = useReactFlow<FlowNode, FlowEdge>();
    const { saveWorkflow } = useWorkflow();
    const updateEdge = useWorkflowStore((state) => state.updateEdge);
    const deleteEdge = useWorkflowStore((state) => state.deleteEdge);
    const [open, setOpen] = useState(false);
    const [isHovered, setIsHovered] = useState(false);

    const parallel = getEdges().filter(
        (e) =>
            (e.source === source && e.target === target) ||
            (e.source === target && e.target === source)
    );

    // 2) if there are two, sort by id and pick an index
    let offsetX = 0;
    let offsetY = 0;
    if (parallel.length > 1) {
        const sorted = parallel.slice().sort((a, b) => a.id.localeCompare(b.id));
        const idx = sorted.findIndex((e) => e.id === id);

        // first edge (idx 0) moves right & down;
        // second edge (idx 1) moves left & up
        if (idx === 0) {
            offsetX = 100;
            offsetY = 0;
        } else {
            offsetX = 0;
            offsetY = -50;
        }
    }

    // Check if this is a self-loop (source and target are the same node)
    const isSelfLoop = source === target;

    // 3) draw the edge path + get label coords
    // Use custom arc path for self-loops, smoothstep for regular edges
    let edgePath: string;
    let labelX: number;
    let labelY: number;

    if (isSelfLoop) {
        // Create a loop arc that goes out and around the node
        const loopRadius = 50;
        const loopOffsetX = 80;
        // Arc path: start from source, curve out and back to target
        edgePath = `M ${sourceX} ${sourceY}
                    C ${sourceX + loopOffsetX} ${sourceY - loopRadius},
                      ${targetX + loopOffsetX} ${targetY + loopRadius},
                      ${targetX} ${targetY}`;
        labelX = sourceX + loopOffsetX;
        labelY = sourceY;
    } else {
        // Use smoothstep path for orthogonal/elbow edges
        // borderRadius: 8 gives slightly rounded corners for a clean look
        // offset: 20 provides spacing before the first bend
        const [path, lx, ly] = getSmoothStepPath({
            sourceX,
            sourceY,
            sourcePosition,
            targetX,
            targetY,
            targetPosition,
            borderRadius: 8,
            offset: 20,
        });
        edgePath = path;
        labelX = lx;
        labelY = ly;
    }

    // Update connected nodes when edge is selected or hovered
    useEffect(() => {
        setNodes((nodes) => {
            return nodes.map((node) => {
                if (node.id === source || node.id === target) {
                    // Update both properties based on edge state
                    const shouldSelectThroughEdge = selected || false;
                    const shouldHoverThroughEdge = isHovered || false;

                    // Only update if state actually changed
                    if (
                        node.data.selected_through_edge !== shouldSelectThroughEdge ||
                        node.data.hovered_through_edge !== shouldHoverThroughEdge
                    ) {
                        return {
                            ...node,
                            data: {
                                ...node.data,
                                selected_through_edge: shouldSelectThroughEdge,
                                hovered_through_edge: shouldHoverThroughEdge
                            }
                        };
                    }
                }
                return node;
            });
        });
    }, [selected, isHovered, source, target, setNodes]);

    const handleSaveEdgeData = useCallback(async (updatedData: FlowEdgeData) => {
        // Use the workflow store's updateEdge method to properly track history
        updateEdge(id, { data: updatedData });
        await saveWorkflow();
    }, [id, updateEdge, saveWorkflow]);

    const handleDeleteEdge = useCallback(() => {
        deleteEdge(id);
    }, [id, deleteEdge]);

    return (
        <>
            <g
                onMouseEnter={() => setIsHovered(true)}
                onMouseLeave={() => setIsHovered(false)}
                onDoubleClick={() => setOpen(true)}
            >
                <BaseEdge
                    id={id}
                    path={edgePath}
                    style={{
                        ...style,
                        // Brand marks selection and hover, as on the steps; idle
                        // connections are a calm solid ink line (Conversation.dc.html),
                        // even on edges saved as `animated`.
                        stroke: selected || isHovered
                            ? 'var(--brand)'
                            : data?.invalid ? 'var(--danger)' : 'var(--ink-3)',
                        strokeWidth: selected ? 2.5 : isHovered ? 2 : 1.5,
                        strokeDasharray: 'none',
                        animation: 'none',
                        transition: 'stroke 0.2s ease, stroke-width 0.2s ease',
                    }}
                    interactionWidth={20}
                />
            </g>
            {/* Always show label, expand on select/hover */}
            <EdgeLabelRenderer>
                <div
                    style={{
                        position: 'absolute',
                        pointerEvents: 'all',
                        transformOrigin: 'center',
                        transform: `translate(-50%, -50%) translate(${labelX + offsetX}px, ${labelY + offsetY}px)`,
                        zIndex: 1000,
                    }}
                    className="nodrag nopan"
                    onMouseEnter={() => setIsHovered(true)}
                    onMouseLeave={() => setIsHovered(false)}
                    onDoubleClick={() => setOpen(true)}
                >
                    {/* Show full EdgeLabel when selected or hovered, otherwise show simple label */}
                    {(selected || isHovered) ? (
                        <div
                            className={cn(
                                "min-w-[220px] max-w-[280px] rounded-lg border bg-panel shadow-panel",
                                "animate-in fade-in zoom-in-95 duration-150",
                                data?.invalid
                                    ? "border-danger"
                                    : selected
                                        ? "border-brand ring-4 ring-brand-dim"
                                        : "border-line",
                            )}
                        >
                            <div className="flex items-center justify-between gap-2 border-b border-line-soft py-1.5 pr-1.5 pl-3">
                                <span className="text-[10.5px] font-semibold tracking-[0.08em] text-ink-3 uppercase">
                                    Move on when
                                </span>
                                <div className="flex items-center gap-0.5">
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        aria-label="Edit connection"
                                        className="size-7 text-ink-3 hover:text-foreground"
                                        onClick={() => setOpen(true)}
                                    >
                                        <Pencil className="size-3.5" />
                                    </Button>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        aria-label="Delete connection"
                                        className="size-7 text-ink-3 hover:bg-danger-dim hover:text-danger"
                                        onClick={handleDeleteEdge}
                                    >
                                        <Trash2 className="size-3.5" />
                                    </Button>
                                </div>
                            </div>
                            <div className="px-3 py-2.5">
                                {data?.invalid && data.validationMessage && (
                                    <p className="mb-1 text-[12px] text-danger">{data.validationMessage}</p>
                                )}
                                <p className={cn(
                                    "break-words text-[13px]",
                                    data?.condition || data?.label ? "text-ink" : "text-ink-3 italic",
                                )}>
                                    {data?.condition || data?.label || "Double-click to say when the agent moves on"}
                                </p>
                            </div>
                        </div>
                    ) : (
                        /* Default label (Conversation.dc.html): a small mono tag on the
                           panel, readable over the dotted canvas without competing
                           with the steps. */
                        <div className={cn(
                            "max-w-[200px] truncate rounded-sm border px-2 py-0.5 font-mono text-[10.5px] font-medium",
                            data?.invalid
                                ? "border-danger/40 bg-danger-dim text-danger"
                                : "border-line bg-panel text-ink-2",
                        )}>
                            {data?.label || data?.condition || 'Set a condition'}
                        </div>
                    )}
                </div>
            </EdgeLabelRenderer>
            <EdgeDetailsDialog
                open={open}
                onOpenChange={setOpen}
                data={data}
                onSave={handleSaveEdgeData}
            />
        </>
    );
}
