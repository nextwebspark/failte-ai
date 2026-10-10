"use client";

import { Plus } from "lucide-react";

import type { IntegrationProvider } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";

import { connectableModes } from "./ConnectDialog";
import { authModeLabel } from "./messages";
import { ProviderIcon } from "./ProviderIcon";

interface ProviderCardProps {
    provider: IntegrationProvider;
    connectedCount: number;
    canConnect: boolean;
    onConnect: () => void;
}

/** A catalog entry: what the integration does and how to connect it. */
export function ProviderCard({ provider, connectedCount, canConnect, onConnect }: ProviderCardProps) {
    const modes = connectableModes(provider);
    const functionsId = `provider-${provider.id}-functions`;
    return (
        <Card className="flex h-full flex-col">
            <CardHeader className="flex flex-row items-start gap-3 space-y-0">
                <ProviderIcon icon={provider.icon} />
                <div className="min-w-0 space-y-1">
                    <CardTitle className="text-base">{provider.title}</CardTitle>
                    <CardDescription>{provider.description}</CardDescription>
                </div>
            </CardHeader>
            <CardContent className="flex-1 space-y-3">
                {provider.tools.length > 0 && (
                    <div>
                        <h3 id={functionsId} className="mb-1.5 font-mono text-[11px] uppercase tracking-wide text-ink-3">
                            What your agents can do
                        </h3>
                        <ul aria-labelledby={functionsId} className="space-y-1 text-sm">
                            {provider.tools.map((tool) => (
                                <li key={tool.name} className="text-ink-2">
                                    <span className="font-mono text-xs text-foreground">{tool.name}</span>
                                    {tool.description && (
                                        <span className="line-clamp-2 block text-xs text-muted-foreground">{tool.description}</span>
                                    )}
                                </li>
                            ))}
                        </ul>
                    </div>
                )}
                {modes.length > 0 && (
                    <p className="text-xs text-muted-foreground">
                        Connect with: {modes.map(authModeLabel).join(" or ")}
                    </p>
                )}
            </CardContent>
            <CardFooter className="flex items-center justify-between gap-3">
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
