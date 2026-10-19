"use client";

import { useCallback, useEffect, useState } from "react";

import { useWorkflow } from "@/app/workflow/[workflowId]/contexts/WorkflowContext";
import type { ToolResponse } from "@/client/types.gen";
import { NodeChip } from "@/components/flow/NodeChip";

/** More tool chips than this collapse into "+N more"; MCP servers can list many functions. */
const MAX_CHIPS = 3;

interface ToolBadgesProps {
    toolUuids: string[];
    onStaleUuidsDetected?: (staleUuids: string[]) => void;
    mcpToolFilters?: Record<string, string[]>;
}

export function ToolBadges({ toolUuids, onStaleUuidsDetected, mcpToolFilters }: ToolBadgesProps) {
    const { tools } = useWorkflow();
    const [selectedTools, setSelectedTools] = useState<ToolResponse[]>([]);

    const processTools = useCallback((toolsData: ToolResponse[]) => {
        const filtered = toolsData.filter(tool => toolUuids.includes(tool.tool_uuid));
        setSelectedTools(filtered);

        // Detect stale UUIDs - this only runs when we have loaded data (not undefined)
        if (onStaleUuidsDetected) {
            const validUuids = new Set(toolsData.map(tool => tool.tool_uuid));
            const staleUuids = toolUuids.filter(uuid => !validUuids.has(uuid));
            if (staleUuids.length > 0) {
                onStaleUuidsDetected(staleUuids);
            }
        }
    }, [toolUuids, onStaleUuidsDetected]);

    useEffect(() => {
        if (toolUuids.length > 0 && tools !== undefined) {
            processTools(tools);
        } else if (toolUuids.length === 0) {
            setSelectedTools([]);
        }
    }, [toolUuids, tools, processTools]);

    // Show loading while data hasn't loaded yet
    if (tools === undefined && toolUuids.length > 0) {
        return <NodeChip tone="sky">…</NodeChip>;
    }

    // One chip per tool; an MCP server shows the functions this step enabled.
    const labels = selectedTools.flatMap((tool) => {
        const enabledFns = tool.category === "mcp" ? (mcpToolFilters?.[tool.tool_uuid] ?? []) : [];
        return enabledFns.length > 0
            ? enabledFns.map((fn) => ({ key: `${tool.tool_uuid}-${fn}`, label: fn }))
            : [{ key: tool.tool_uuid, label: tool.name }];
    });
    const shown = labels.slice(0, MAX_CHIPS);
    const hidden = labels.slice(MAX_CHIPS);

    return (
        <>
            {shown.map(({ key, label }) => (
                <NodeChip key={key} tone="sky" title={label}>
                    {label}
                </NodeChip>
            ))}
            {hidden.length > 0 && (
                <NodeChip tone="sky" title={hidden.map((h) => h.label).join(", ")}>
                    +{hidden.length} more
                </NodeChip>
            )}
        </>
    );
}
