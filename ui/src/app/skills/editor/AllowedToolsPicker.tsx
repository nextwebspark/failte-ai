"use client";

import type { ToolResponse } from "@/client/types.gen";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";

import { MAX_ALLOWED_TOOLS } from "../validation";

interface AllowedToolsPickerProps {
    /** null: no restriction; a list (possibly empty): only these tools. */
    value: string[] | null;
    onChange: (value: string[] | null) => void;
    tools: ToolResponse[];
    /** Set when the workspace tools couldn't be loaded. */
    toolsError?: string | null;
    disabled?: boolean;
}

export function allowedToolsSummary(value: readonly string[] | null): string {
    if (value === null) return "The agent keeps all of the step's tools while this skill is loaded.";
    if (value.length === 0) {
        return "While this skill is loaded the agent can't call any of the step's tools. Moving to another step and loading skills still work.";
    }
    return `While this skill is loaded the agent can only use the ${value.length} selected ${
        value.length === 1 ? "tool" : "tools"
    } (plus moving to another step and loading skills).`;
}

export function AllowedToolsPicker({
    value,
    onChange,
    tools,
    toolsError = null,
    disabled = false,
}: AllowedToolsPickerProps) {
    const restricted = value !== null;
    const selected = new Set(value ?? []);
    const known = new Set(tools.map((t) => t.tool_uuid));
    const unknown = (value ?? []).filter((uuid) => !known.has(uuid));
    const activeTools = tools.filter((t) => t.status !== "archived" || selected.has(t.tool_uuid));

    const toggle = (uuid: string, checked: boolean) => {
        const next = checked ? [...(value ?? []), uuid] : (value ?? []).filter((u) => u !== uuid);
        onChange(next);
    };

    return (
        <fieldset className="space-y-3" disabled={disabled}>
            <legend className="text-sm font-medium">Allowed tools</legend>
            <p className="text-xs text-muted-foreground">
                When this skill is loaded the agent can only use these tools. Use it to keep a playbook on track,
                for example a refund flow that should only look up orders.
            </p>
            <RadioGroup
                value={restricted ? "only" : "any"}
                onValueChange={(next) => onChange(next === "only" ? [...selected] : null)}
                className="gap-2"
                aria-label="Tool restriction"
                disabled={disabled}
            >
                <div className="flex items-center gap-2">
                    <RadioGroupItem value="any" id="allowed-any" />
                    <Label htmlFor="allowed-any" className="text-sm font-normal">
                        No restriction
                    </Label>
                </div>
                <div className="flex items-center gap-2">
                    <RadioGroupItem value="only" id="allowed-only" />
                    <Label htmlFor="allowed-only" className="text-sm font-normal">
                        Only selected tools
                    </Label>
                </div>
            </RadioGroup>

            {toolsError && (
                <p className="text-xs text-destructive" role="alert">
                    {toolsError.replace(/\.$/, "")}. Selected tools show by ID until the list loads; reload the page to try again.
                </p>
            )}
            {restricted && (
                <div className="max-h-64 overflow-y-auto rounded-md border border-line">
                    {activeTools.length === 0 && unknown.length === 0 ? (
                        <p className="p-3 text-sm text-muted-foreground">
                            {toolsError ? "Tools are unavailable right now." : "This workspace has no tools yet."}
                        </p>
                    ) : (
                        <ul className="divide-y divide-line-soft">
                            {activeTools.map((tool) => {
                                const id = `allowed-tool-${tool.tool_uuid}`;
                                const checked = selected.has(tool.tool_uuid);
                                return (
                                    <li key={tool.tool_uuid} className="flex items-start gap-3 p-2.5">
                                        <Checkbox
                                            id={id}
                                            checked={checked}
                                            disabled={disabled || (!checked && selected.size >= MAX_ALLOWED_TOOLS)}
                                            onCheckedChange={(next) => toggle(tool.tool_uuid, next === true)}
                                        />
                                        <Label htmlFor={id} className="grid gap-0.5 text-sm font-normal">
                                            <span className="font-medium">{tool.name}</span>
                                            {tool.description && (
                                                <span className="line-clamp-1 text-xs text-muted-foreground">
                                                    {tool.description}
                                                </span>
                                            )}
                                        </Label>
                                    </li>
                                );
                            })}
                            {unknown.map((uuid) => (
                                <li key={uuid} className="flex items-center gap-3 p-2.5">
                                    <Checkbox
                                        id={`allowed-tool-${uuid}`}
                                        checked
                                        disabled={disabled}
                                        onCheckedChange={() => toggle(uuid, false)}
                                    />
                                    <Label htmlFor={`allowed-tool-${uuid}`} className="text-sm font-normal">
                                        {toolsError ? "Tool" : "Unknown or deleted tool"} <span className="font-mono text-xs">{uuid}</span>
                                    </Label>
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            )}
            <p className="text-xs text-ink-2" role="status">
                {allowedToolsSummary(value)}
            </p>
        </fieldset>
    );
}
