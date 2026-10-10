"use client";

import { useMemo, useState } from "react";

import type {
    IntegrationConnectionResponse,
    IntegrationProvider,
    ProviderAppResponse,
} from "@/client/types.gen";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { authModeLabel, credentialFamily, isEmail } from "./messages";
import { NoAuthConnect } from "./NoAuthConnect";
import { OAuthConnect } from "./OAuthConnect";
import { type ReusableKey, ServiceAccountConnect } from "./ServiceAccountConnect";

/** Auth modes this screen can drive, in the order they are offered. */
export const SUPPORTED_AUTH_MODES = ["oauth2", "service_account", "none"] as const;
type SupportedMode = (typeof SUPPORTED_AUTH_MODES)[number];

export function connectableModes(provider: IntegrationProvider): SupportedMode[] {
    return SUPPORTED_AUTH_MODES.filter((mode) => provider.auth_modes.includes(mode));
}

export interface ConnectTarget {
    provider: IntegrationProvider;
    /** Set when reconnecting an errored connection. */
    replaces?: IntegrationConnectionResponse;
}

/**
 * Active connections of the same auth family as `provider` (e.g. the Google
 * Calendar connection when connecting Google Sheets), by auth mode.
 */
export function familyConnections(
    provider: IntegrationProvider,
    providers: IntegrationProvider[],
    connections: IntegrationConnectionResponse[],
    authMode: string,
): ReusableKey[] {
    const family = credentialFamily(provider);
    const byId = new Map(providers.map((p) => [p.id, p]));
    const seen = new Set<string>();
    const found: ReusableKey[] = [];
    for (const c of connections) {
        const other = byId.get(c.provider);
        if (!other || credentialFamily(other) !== family) continue;
        if (c.status !== "active" || c.auth_mode !== authMode || !c.account_label) continue;
        if (seen.has(c.account_label)) continue;
        seen.add(c.account_label);
        found.push({ connectionId: c.id, label: c.account_label });
    }
    return found;
}

interface ConnectDialogProps {
    target: ConnectTarget | null;
    providerApps: ProviderAppResponse[];
    /** The catalog and this workspace's connections, to offer what is already connected. */
    providers?: IntegrationProvider[];
    connections?: IntegrationConnectionResponse[];
    onOpenChange: (open: boolean) => void;
    onInstalled: (connection: IntegrationConnectionResponse, replaces?: IntegrationConnectionResponse) => void;
    onProviderAppCreated: (app: ProviderAppResponse) => void;
}

export function ConnectDialog({
    target,
    providerApps,
    providers = [],
    connections = [],
    onOpenChange,
    onInstalled,
    onProviderAppCreated,
}: ConnectDialogProps) {
    return (
        <Dialog open={target !== null} onOpenChange={onOpenChange}>
            <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
                {target && (
                    // Keyed so each open starts from a clean form (and drops any pasted key).
                    <ConnectBody
                        key={`${target.provider.id}:${target.replaces?.id ?? ""}`}
                        target={target}
                        providerApps={providerApps}
                        providers={providers}
                        connections={connections}
                        onClose={() => onOpenChange(false)}
                        onInstalled={onInstalled}
                        onProviderAppCreated={onProviderAppCreated}
                    />
                )}
            </DialogContent>
        </Dialog>
    );
}

function ConnectBody({
    target,
    providerApps,
    providers,
    connections,
    onClose,
    onInstalled,
    onProviderAppCreated,
}: {
    target: ConnectTarget;
    providerApps: ProviderAppResponse[];
    providers: IntegrationProvider[];
    connections: IntegrationConnectionResponse[];
    onClose: () => void;
    onInstalled: ConnectDialogProps["onInstalled"];
    onProviderAppCreated: ConnectDialogProps["onProviderAppCreated"];
}) {
    const { provider, replaces } = target;
    const modes = connectableModes(provider);
    const preferred = modes.find((m) => m === replaces?.auth_mode) ?? modes[0];
    const [mode, setMode] = useState<SupportedMode | undefined>(preferred);
    const reusableKeys = useMemo(
        () => familyConnections(provider, providers, connections, "service_account"),
        [provider, providers, connections],
    );
    const oauthAccounts = useMemo(() => {
        // Only email addresses can be a sign-in hint. When reconnecting, the
        // replaced connection's account comes first (it may be in error).
        const accounts = familyConnections(provider, providers, connections, "oauth2").filter((a) =>
            isEmail(a.label),
        );
        const previous = replaces?.auth_mode === "oauth2" ? replaces.account_label : null;
        if (!isEmail(previous)) return accounts;
        return [
            { connectionId: replaces?.id ?? previous, label: previous },
            ...accounts.filter((a) => a.label !== previous),
        ];
    }, [provider, providers, connections, replaces]);

    return (
        <>
            <DialogHeader>
                <DialogTitle>{replaces ? `Reconnect ${provider.title}` : `Connect ${provider.title}`}</DialogTitle>
                <DialogDescription>
                    {replaces
                        ? "Connect again to restore access. You can remove the old connection afterwards."
                        : "Your agents get this integration's functions as an agent tool once it's connected."}
                </DialogDescription>
            </DialogHeader>

            {modes.length > 1 && mode && (
                <div className="grid gap-2">
                    <span id="connect-mode-label" className="text-sm font-medium">
                        How do you want to connect?
                    </span>
                    <Tabs value={mode} onValueChange={(v) => setMode(modes.find((m) => m === v) ?? mode)}>
                        <TabsList aria-labelledby="connect-mode-label">
                            {modes.map((m) => (
                                <TabsTrigger key={m} value={m}>
                                    {authModeLabel(m)}
                                </TabsTrigger>
                            ))}
                        </TabsList>
                    </Tabs>
                </div>
            )}

            {mode === "oauth2" && (
                <OAuthConnect
                    provider={provider}
                    providerApps={providerApps}
                    knownAccounts={oauthAccounts}
                    replacesConnectionId={replaces?.id}
                    onCancel={onClose}
                    onProviderAppCreated={onProviderAppCreated}
                />
            )}
            {mode === "service_account" && (
                <ServiceAccountConnect
                    provider={provider}
                    reusable={reusableKeys}
                    preferNewKey={Boolean(replaces)}
                    onCancel={onClose}
                    onInstalled={(connection) => {
                        onInstalled(connection, replaces);
                        onClose();
                    }}
                />
            )}
            {mode === "none" && (
                <NoAuthConnect
                    provider={provider}
                    onCancel={onClose}
                    onInstalled={(connection) => {
                        onInstalled(connection, replaces);
                        onClose();
                    }}
                />
            )}
            {!mode && (
                <p className="text-sm text-muted-foreground">
                    This integration can&apos;t be connected from here yet.
                </p>
            )}
        </>
    );
}
