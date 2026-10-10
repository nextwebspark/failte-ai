"use client";

import { useState } from "react";

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

import { authModeLabel } from "./messages";
import { OAuthConnect } from "./OAuthConnect";
import { ServiceAccountConnect } from "./ServiceAccountConnect";

/** Auth modes this screen can drive, in the order they are offered. */
export const SUPPORTED_AUTH_MODES = ["oauth2", "service_account"] as const;
type SupportedMode = (typeof SUPPORTED_AUTH_MODES)[number];

export function connectableModes(provider: IntegrationProvider): SupportedMode[] {
    return SUPPORTED_AUTH_MODES.filter((mode) => provider.auth_modes.includes(mode));
}

export interface ConnectTarget {
    provider: IntegrationProvider;
    /** Set when reconnecting an errored connection. */
    replaces?: IntegrationConnectionResponse;
}

interface ConnectDialogProps {
    target: ConnectTarget | null;
    providerApps: ProviderAppResponse[];
    onOpenChange: (open: boolean) => void;
    onInstalled: (connection: IntegrationConnectionResponse, replaces?: IntegrationConnectionResponse) => void;
    onProviderAppCreated: (app: ProviderAppResponse) => void;
}

export function ConnectDialog({ target, providerApps, onOpenChange, onInstalled, onProviderAppCreated }: ConnectDialogProps) {
    return (
        <Dialog open={target !== null} onOpenChange={onOpenChange}>
            <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
                {target && (
                    // Keyed so each open starts from a clean form (and drops any pasted key).
                    <ConnectBody
                        key={`${target.provider.id}:${target.replaces?.id ?? ""}`}
                        target={target}
                        providerApps={providerApps}
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
    onClose,
    onInstalled,
    onProviderAppCreated,
}: {
    target: ConnectTarget;
    providerApps: ProviderAppResponse[];
    onClose: () => void;
    onInstalled: ConnectDialogProps["onInstalled"];
    onProviderAppCreated: ConnectDialogProps["onProviderAppCreated"];
}) {
    const { provider, replaces } = target;
    const modes = connectableModes(provider);
    const preferred = modes.find((m) => m === replaces?.auth_mode) ?? modes[0];
    const [mode, setMode] = useState<SupportedMode | undefined>(preferred);

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
                    replacesConnectionId={replaces?.id}
                    onCancel={onClose}
                    onProviderAppCreated={onProviderAppCreated}
                />
            )}
            {mode === "service_account" && (
                <ServiceAccountConnect
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
