"use client";

import { ChevronDown, Plus } from "lucide-react";
import { useId, useState } from "react";

import type { IntegrationProvider, IntegrationToolSummary } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";

import { connectableModes } from "./ConnectDialog";
import { authModeLabel, humanToolName } from "./messages";
import { ProviderIcon } from "./ProviderIcon";

/** One short line per integration for the catalog card; others show their own description. */
const SHORT_DESCRIPTIONS: Record<string, string> = {
    calendly: "Offer times from a Calendly event and book callers in.",
    "google-calendar": "Offer free times and book callers into Google Calendar.",
    "outlook-calendar": "Offer free times and book callers into Outlook.",
    "google-sheets": "Find rows, add rows and look up orders in a sheet.",
    "website-catalogue": "Answer questions on your products, prices and stock.",
};

/** The card's one-line description. */
export function shortDescription(provider: Pick<IntegrationProvider, "id" | "description">): string {
    return SHORT_DESCRIPTIONS[provider.id] ?? provider.description;
}

interface ProviderCardProps {
    provider: IntegrationProvider;
    connectedCount: number;
    canConnect: boolean;
    onConnect: () => void;
}

/**
 * A catalog entry: what the integration is in one line, and how to connect it.
 * "Explore" opens what agents can do with it and how it connects. Functions
 * show their short human summary only; the long instructions are for agents.
 */
export function ProviderCard({ provider, connectedCount, canConnect, onConnect }: ProviderCardProps) {
    const modes = connectableModes(provider);
    const panelId = `provider-${useId().replace(/:/g, "")}-details`;
    const headingId = `${panelId}-heading`;
    const [open, setOpen] = useState(false);
    const tools = provider.tools;
    const hasDetails = tools.length > 0 || modes.length > 0;

    return (
        <Card className="flex h-full flex-col">
            <CardHeader className="flex flex-row items-start gap-3 space-y-0">
                <ProviderIcon icon={provider.icon} />
                <div className="min-w-0 space-y-1">
                    <CardTitle className="text-base">{provider.title}</CardTitle>
                    <CardDescription>{shortDescription(provider)}</CardDescription>
                </div>
            </CardHeader>
            {hasDetails && open && (
                <CardContent id={panelId} className="space-y-3">
                    <div className="rounded-md border border-line bg-panel-2 p-3">
                        {tools.length > 0 && (
                            <>
                                <h3
                                    id={headingId}
                                    className="mb-1.5 text-meta font-semibold uppercase tracking-[0.08em] text-ink-3"
                                >
                                    What your agents can do
                                </h3>
                                <ul aria-labelledby={headingId} className="space-y-0.5 text-sm text-ink-2">
                                    {tools.map((tool: IntegrationToolSummary) => (
                                        <li key={tool.name} title={tool.name}>
                                            {humanToolName(tool)}
                                        </li>
                                    ))}
                                </ul>
                            </>
                        )}
                        {modes.length > 0 && (
                            <p className={tools.length > 0 ? "mt-3 text-xs text-muted-foreground" : "text-xs text-muted-foreground"}>
                                Connect with: {modes.map((m) => authModeLabel(m, provider.id)).join(" or ")}
                            </p>
                        )}
                    </div>
                </CardContent>
            )}
            <CardFooter className="mt-auto flex flex-col items-stretch gap-3">
                <span className="text-xs text-ink-3">
                    {connectedCount > 0
                        ? `${connectedCount} connection${connectedCount === 1 ? "" : "s"}`
                        : "Not connected"}
                </span>
                <div className="flex flex-wrap items-center gap-2">
                    {canConnect && modes.length > 0 && (
                        <Button size="sm" variant={connectedCount > 0 ? "soft" : "default"} onClick={onConnect}>
                            <Plus aria-hidden />
                            {connectedCount > 0 ? "Add another" : "Connect"}
                        </Button>
                    )}
                    {hasDetails && (
                        <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            aria-expanded={open}
                            aria-controls={panelId}
                            aria-label={`Explore ${provider.title}`}
                            onClick={() => setOpen((v) => !v)}
                        >
                            Explore
                            <ChevronDown className={open ? "rotate-180 transition-transform" : "transition-transform"} aria-hidden />
                        </Button>
                    )}
                </div>
            </CardFooter>
        </Card>
    );
}
