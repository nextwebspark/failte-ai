"use client";

import { ChevronDown, Plus } from "lucide-react";
import { useState } from "react";

import type { IntegrationProvider, IntegrationToolSummary } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";

import { connectableModes } from "./ConnectDialog";
import { authModeLabel, humanToolName } from "./messages";
import { ProviderIcon } from "./ProviderIcon";

/** Functions listed before "Show all". */
const COLLAPSED_TOOLS = 3;

interface ProviderCardProps {
    provider: IntegrationProvider;
    connectedCount: number;
    canConnect: boolean;
    onConnect: () => void;
}

/**
 * A catalog entry: what the integration does and how to connect it. Functions
 * show their short human summary only; the long instructions are for agents.
 */
export function ProviderCard({ provider, connectedCount, canConnect, onConnect }: ProviderCardProps) {
    const modes = connectableModes(provider);
    const functionsId = `provider-${provider.id}-functions`;
    const listId = `${functionsId}-list`;
    const [expanded, setExpanded] = useState(false);
    const tools = provider.tools;
    const shown = expanded ? tools : tools.slice(0, COLLAPSED_TOOLS);

    return (
        <Card className="flex flex-col">
            <CardHeader className="flex flex-row items-start gap-3 space-y-0">
                <ProviderIcon icon={provider.icon} />
                <div className="min-w-0 space-y-1">
                    <CardTitle className="text-base">{provider.title}</CardTitle>
                    <CardDescription>{provider.description}</CardDescription>
                </div>
            </CardHeader>
            <CardContent className="space-y-3">
                {tools.length > 0 && (
                    <div>
                        <h3 id={functionsId} className="mb-1.5 font-mono text-[11px] uppercase tracking-wide text-ink-3">
                            What your agents can do
                        </h3>
                        <ul id={listId} aria-labelledby={functionsId} className="space-y-0.5 text-sm text-ink-2">
                            {shown.map((tool: IntegrationToolSummary) => (
                                <li key={tool.name} title={tool.name}>
                                    {humanToolName(tool)}
                                </li>
                            ))}
                        </ul>
                        {tools.length > COLLAPSED_TOOLS && (
                            <Button
                                type="button"
                                variant="link"
                                size="sm"
                                className="mt-1 h-auto px-0 text-xs"
                                aria-expanded={expanded}
                                aria-controls={listId}
                                onClick={() => setExpanded((v) => !v)}
                            >
                                {expanded ? "Show fewer" : `Show all ${tools.length}`}
                                <ChevronDown className={expanded ? "rotate-180" : undefined} aria-hidden />
                            </Button>
                        )}
                    </div>
                )}
                {modes.length > 0 && (
                    <p className="text-xs text-muted-foreground">
                        Connect with: {modes.map(authModeLabel).join(" or ")}
                    </p>
                )}
            </CardContent>
            <CardFooter className="mt-auto flex items-center justify-between gap-3">
                <span className="text-xs text-ink-3">
                    {connectedCount > 0
                        ? `${connectedCount} connection${connectedCount === 1 ? "" : "s"}`
                        : "Not connected"}
                </span>
                {canConnect && modes.length > 0 && (
                    <Button size="sm" variant={connectedCount > 0 ? "soft" : "default"} onClick={onConnect}>
                        <Plus aria-hidden />
                        {connectedCount > 0 ? "Add another" : "Connect"}
                    </Button>
                )}
            </CardFooter>
        </Card>
    );
}
