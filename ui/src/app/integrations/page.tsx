"use client";

import { Loader2, Plug, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import {
    syncConnectionApiV1IntegrationsConnectionsConnectionIdSyncPost,
    testConnectionApiV1IntegrationsConnectionsConnectionIdTestPost,
    uninstallIntegrationApiV1IntegrationsConnectionsConnectionIdDelete,
} from "@/client/sdk.gen";
import type { IntegrationConnectionResponse, IntegrationProvider } from "@/client/types.gen";
import { NoAccess } from "@/components/auth/NoAccess";
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { SectionHeading, SectionHint } from "@/components/ui/section-heading";
import { Skeleton } from "@/components/ui/skeleton";
import { BRAND } from "@/config/brand";
import { useOrgConfig } from "@/context/OrgConfigContext";

import { ConfigDialog } from "./ConfigDialog";
import { ConnectDialog, type ConnectTarget } from "./ConnectDialog";
import { type ConnectionAction, ConnectionCard } from "./ConnectionCard";
import {
    integrationErrorMessage,
    isSyncing,
    oauthFailureMessage,
    parseIntegrationReturn,
    urlWithoutReturnParams,
} from "./messages";
import { activateConnection } from "./oauthCalls";
import { clearPendingOAuth, takePendingOAuth } from "./pendingOAuth";
import { ProviderCard } from "./ProviderCard";
import { fieldsFromSchema, hasRequiredConfig } from "./schemaForm";
import { useIntegrations } from "./useIntegrations";

interface ConfigTarget {
    connection: IntegrationConnectionResponse;
    justConnected: boolean;
}

const NETWORK_ERROR = "Couldn't reach the server. Please try again.";
/** How often connections are reloaded while a sync runs. */
const SYNC_POLL_MS = 4000;
const NOT_CONFIRMED =
    "This sign-in can't be confirmed here. Finish connecting in the same browser tab you started from, within 10 minutes.";

export default function IntegrationsPage() {
    const { can, role, loading: orgLoading } = useOrgConfig();
    const canRead = can("integrations:read");
    if (!canRead) {
        // The role is still loading: render nothing rather than flash "no access".
        if (role === null && orgLoading) return null;
        return <NoAccess role={role} />;
    }
    return <IntegrationsScreen />;
}

function IntegrationsScreen() {
    const { can } = useOrgConfig();
    const canWrite = can("integrations:write");
    const canInstall = can("integrations:write", "agents:write");
    const canOpenTool = can("agents:write");
    const {
        providers,
        connections,
        providerApps,
        loading,
        unavailable,
        error,
        refresh,
        refreshConnections,
        reloadConnectionsQuietly,
        upsertConnection,
        addProviderApp,
    } = useIntegrations(true);

    const [connectTarget, setConnectTarget] = useState<ConnectTarget | null>(null);
    const [configTarget, setConfigTarget] = useState<ConfigTarget | null>(null);
    /** A just-connected connection whose required settings to offer for review. */
    const [pendingReview, setPendingReview] = useState<IntegrationConnectionResponse | null>(null);
    /** The errored connection a reconnect replaced, offered for removal. */
    const [replaceCandidate, setReplaceCandidate] = useState<string | null>(null);
    const [busy, setBusy] = useState<{ id: string; action: ConnectionAction } | null>(null);
    const [finishing, setFinishing] = useState(false);
    const [returnError, setReturnError] = useState<string | null>(null);

    const providerById = useMemo(() => new Map(providers.map((p) => [p.id, p])), [providers]);
    const providersWithSettings = useMemo(
        () => new Set(providers.filter((p) => fieldsFromSchema(p.config_schema).length > 0).map((p) => p.id)),
        [providers],
    );
    const titleOf = useCallback(
        (providerId: string) => providerById.get(providerId)?.title ?? providerId,
        [providerById],
    );

    // -- OAuth return: /integrations?integration_result=… ----------------------
    // Runs once, after the first load: activating earlier would race the initial
    // connections list, which could then overwrite the activated connection.
    const handledReturn = useRef(false);
    useEffect(() => {
        if (loading || handledReturn.current) return;
        const result = parseIntegrationReturn(new URLSearchParams(window.location.search));
        if (!result) return;
        handledReturn.current = true;
        window.history.replaceState(window.history.state, "", urlWithoutReturnParams(window.location.href));

        if (result.kind === "error") {
            clearPendingOAuth();
            setReturnError(oauthFailureMessage(result.reason));
            return;
        }

        const pending = result.provider ? takePendingOAuth(result.provider) : null;
        if (!pending) {
            clearPendingOAuth();
            setReturnError(NOT_CONFIRMED);
            return;
        }
        setFinishing(true);
        void (async () => {
            try {
                const response = await activateConnection(result.connectionId, pending.nonce);
                if (response.error || !response.data) {
                    setReturnError(integrationErrorMessage(response.error, "Couldn't finish connecting. Please try again."));
                    return;
                }
                const connected = response.data;
                upsertConnection(connected);
                toast.success(connected.account_label ? `Connected as ${connected.account_label}` : "Connected");
                await refreshConnections();
                if (pending.replacesConnectionId) setReplaceCandidate(pending.replacesConnectionId);
                setPendingReview(connected);
            } catch {
                setReturnError("Couldn't reach the server to finish connecting. Please try again.");
            } finally {
                setFinishing(false);
            }
        })();
    }, [loading, refreshConnections, upsertConnection]);

    // Offer required settings for review (the catalog is loaded by now).
    useEffect(() => {
        if (!pendingReview) return;
        const provider = providerById.get(pendingReview.provider);
        if (provider && hasRequiredConfig(provider.config_schema) && canWrite) {
            setConfigTarget({ connection: pendingReview, justConnected: true });
        }
        setPendingReview(null);
    }, [pendingReview, providerById, canWrite]);

    // While any sync runs, reload the connections so its status updates.
    const anySyncing = connections.some((c) => isSyncing(c.sync));
    useEffect(() => {
        if (!anySyncing) return;
        const timer = window.setInterval(() => void reloadConnectionsQuietly(), SYNC_POLL_MS);
        return () => window.clearInterval(timer);
    }, [anySyncing, reloadConnectionsQuietly]);

    const startSync = useCallback(
        async (connection: IntegrationConnectionResponse) => {
            const response = await syncConnectionApiV1IntegrationsConnectionsConnectionIdSyncPost({
                path: { connection_id: connection.id },
            });
            if (response.error || !response.data) {
                toast.error(integrationErrorMessage(response.error, "Couldn't start the sync"));
                return;
            }
            upsertConnection({ ...connection, sync: response.data });
            const label = providerById.get(connection.provider)?.sync_item_label ?? "data";
            toast.success(`Importing ${label} in the background`);
        },
        [providerById, upsertConnection],
    );

    // -- connection actions ------------------------------------------------------
    const removeConnection = useCallback(
        async (connection: IntegrationConnectionResponse) => {
            try {
                const response = await uninstallIntegrationApiV1IntegrationsConnectionsConnectionIdDelete({
                    path: { connection_id: connection.id },
                });
                if (response.error) {
                    toast.error(integrationErrorMessage(response.error, "Couldn't remove the connection"));
                    return;
                }
                toast.success(`${titleOf(connection.provider)} connection removed`);
                await refreshConnections();
            } catch {
                toast.error(NETWORK_ERROR);
            }
        },
        [refreshConnections, titleOf],
    );

    const runAction = async (connection: IntegrationConnectionResponse, action: ConnectionAction) => {
        const provider = providerById.get(connection.provider);
        if (action === "configure") {
            setConfigTarget({ connection, justConnected: false });
            return;
        }
        if (action === "reconnect") {
            if (!provider) {
                toast.error("This integration is no longer available to connect.");
                return;
            }
            setConnectTarget({ provider, replaces: connection });
            return;
        }

        setBusy({ id: connection.id, action });
        try {
            if (action === "test") {
                const response = await testConnectionApiV1IntegrationsConnectionsConnectionIdTestPost({
                    path: { connection_id: connection.id },
                });
                if (response.error || !response.data) {
                    toast.error(integrationErrorMessage(response.error, "Couldn't test the connection"));
                    return;
                }
                upsertConnection(response.data.connection);
                if (response.data.ok) toast.success(response.data.message || "The connection works");
                else toast.error(response.data.message || "The connection test failed");
            } else if (action === "finish") {
                const response = await activateConnection(connection.id);
                if (response.error || !response.data) {
                    toast.error(integrationErrorMessage(response.error, "Couldn't finish setting up the connection"));
                    return;
                }
                upsertConnection(response.data);
                toast.success(`${titleOf(connection.provider)} is ready for your agents`);
            } else if (action === "remove") {
                await removeConnection(connection);
            } else if (action === "sync") {
                await startSync(connection);
            }
        } catch {
            toast.error(NETWORK_ERROR);
        } finally {
            setBusy(null);
        }
    };

    const onInstalled = (connection: IntegrationConnectionResponse, replaces?: IntegrationConnectionResponse) => {
        upsertConnection(connection);
        toast.success(`${titleOf(connection.provider)} connected`);
        if (replaces) setReplaceCandidate(replaces.id);
        // A catalogue is empty until synced: start the first import right away.
        if (providerById.get(connection.provider)?.capabilities?.includes("sync") && !connection.sync) {
            void startSync(connection).catch(() => toast.error(NETWORK_ERROR));
        }
    };

    const oldConnection = connections.find((c) => c.id === replaceCandidate) ?? null;
    const connectionCounts = useMemo(() => {
        const counts = new Map<string, number>();
        for (const c of connections) counts.set(c.provider, (counts.get(c.provider) ?? 0) + 1);
        return counts;
    }, [connections]);

    return (
        <div className="page-body">
            <div className="w-full max-w-5xl space-y-8">
                {finishing && (
                    <Panel accent="sky" padding="sm" className="flex items-center gap-2 text-sm" role="status">
                        <Loader2 className="size-4 animate-spin" aria-hidden />
                        Finishing your connection…
                    </Panel>
                )}
                {returnError && (
                    <Panel accent="danger" padding="sm" className="flex items-start gap-3" role="alert">
                        <div className="flex-1 text-sm">
                            <p className="font-medium">The connection wasn&apos;t completed</p>
                            <p className="mt-0.5 text-ink-2">{returnError}</p>
                        </div>
                        <Button
                            variant="ghost"
                            size="icon"
                            className="size-7"
                            onClick={() => setReturnError(null)}
                            aria-label="Dismiss"
                        >
                            <X aria-hidden />
                        </Button>
                    </Panel>
                )}

                {unavailable ? (
                    <UnavailableState />
                ) : error ? (
                    <Panel accent="danger" padding="sm" className="flex flex-wrap items-center justify-between gap-3">
                        <p className="text-sm text-destructive">{error}</p>
                        <Button size="sm" variant="soft" onClick={() => void refresh()}>
                            Try again
                        </Button>
                    </Panel>
                ) : loading ? (
                    <LoadingState />
                ) : (
                    <>
                        {!canInstall && (
                            <p className="text-sm text-muted-foreground">
                                You can view integrations. Ask a workspace admin or developer to connect or remove them.
                            </p>
                        )}
                        <section>
                            <SectionHeading action={<SectionHint>{connections.length} total</SectionHint>}>
                                Your connections
                            </SectionHeading>
                            {connections.length === 0 ? (
                                <Panel padding="sm">
                                    <p className="text-sm text-ink-2">
                                        No connections yet.
                                        {canInstall && " Pick an integration below to connect it."}
                                    </p>
                                </Panel>
                            ) : (
                                <div className="grid gap-3">
                                    {connections.map((connection) => (
                                        <ConnectionCard
                                            key={connection.id}
                                            connection={connection}
                                            provider={providerById.get(connection.provider)}
                                            hasSettings={providersWithSettings.has(connection.provider)}
                                            permissions={{ canWrite, canInstall, canOpenTool }}
                                            busy={busy?.id === connection.id ? busy.action : null}
                                            onAction={(action) => void runAction(connection, action)}
                                        />
                                    ))}
                                </div>
                            )}
                        </section>

                        <section>
                            <SectionHeading>Available integrations</SectionHeading>
                            {providers.length === 0 ? (
                                <p className="text-sm text-muted-foreground">No integrations are available yet.</p>
                            ) : (
                                <div className="grid items-start gap-4 sm:grid-cols-2 xl:grid-cols-3">
                                    {providers.map((provider: IntegrationProvider) => (
                                        <ProviderCard
                                            key={provider.id}
                                            provider={provider}
                                            connectedCount={connectionCounts.get(provider.id) ?? 0}
                                            canConnect={canInstall}
                                            onConnect={() => setConnectTarget({ provider })}
                                        />
                                    ))}
                                </div>
                            )}
                        </section>
                    </>
                )}
            </div>

            <ConnectDialog
                target={connectTarget}
                providerApps={providerApps}
                providers={providers}
                connections={connections}
                onOpenChange={(open) => !open && setConnectTarget(null)}
                onInstalled={onInstalled}
                onProviderAppCreated={addProviderApp}
            />

            <ConfigDialog
                connection={configTarget?.connection ?? null}
                provider={configTarget ? providerById.get(configTarget.connection.provider) : undefined}
                justConnected={configTarget?.justConnected ?? false}
                onOpenChange={(open) => !open && setConfigTarget(null)}
                onSaved={upsertConnection}
            />

            <AlertDialog
                open={oldConnection !== null && canInstall && !configTarget && !connectTarget}
                onOpenChange={(open) => !open && setReplaceCandidate(null)}
            >
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Remove the old connection?</AlertDialogTitle>
                        <AlertDialogDescription>
                            The new {oldConnection ? titleOf(oldConnection.provider) : ""} connection is working. The
                            old one{oldConnection?.account_label ? ` (${oldConnection.account_label})` : ""} still needs
                            attention. Removing it archives its agent tool, so switch any agents using that tool to the
                            new one.
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>Keep it</AlertDialogCancel>
                        <AlertDialogAction
                            className="bg-destructive text-white hover:bg-destructive/90"
                            onClick={() => {
                                if (oldConnection) void removeConnection(oldConnection);
                                setReplaceCandidate(null);
                            }}
                        >
                            Remove old connection
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>
    );
}

function UnavailableState() {
    return (
        <div className="mx-auto flex max-w-md flex-col items-center gap-3 py-16 text-center">
            <Plug className="size-8 text-ink-3" aria-hidden />
            <h2 className="text-lg font-semibold">Integrations aren&apos;t configured on this server</h2>
            <p className="text-sm text-muted-foreground">
                Connecting apps like Google Calendar needs the integrations service, which isn&apos;t set up for this{" "}
                {BRAND.name} deployment. Ask your administrator to enable it.
            </p>
        </div>
    );
}

function LoadingState() {
    return (
        <div className="space-y-8" aria-busy="true" aria-label="Loading integrations">
            <div className="space-y-3">
                <Skeleton className="h-5 w-40" />
                <Skeleton className="h-20 w-full" />
            </div>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {[0, 1, 2].map((i) => (
                    <Skeleton key={i} className="h-56 w-full" />
                ))}
            </div>
        </div>
    );
}
