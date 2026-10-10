"use client";

import { ArrowUpRight, CloudDownload, Loader2, PlugZap, RefreshCw, Settings2, Trash2, Wrench } from "lucide-react";
import Link from "next/link";

import type { IntegrationConnectionResponse, IntegrationProvider } from "@/client/types.gen";
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { StatusPill, type StatusTone } from "@/components/ui/status-pill";

import {
    authModeLabel,
    connectionErrorMessage,
    type ConnectionState,
    connectionState,
    isSyncing,
    needsReconnect,
    syncSummary,
} from "./messages";
import { ProviderIcon } from "./ProviderIcon";

const STATE_PILL: Record<ConnectionState, { tone: StatusTone; label: string }> = {
    active: { tone: "ok", label: "Connected" },
    pending: { tone: "warn", label: "Awaiting confirmation" },
    not_installed: { tone: "warn", label: "Setup incomplete" },
    error: { tone: "bad", label: "Needs attention" },
    revoked: { tone: "mute", label: "Removed" },
};

export type ConnectionAction = "test" | "configure" | "reconnect" | "finish" | "remove" | "sync";

export interface ConnectionPermissions {
    /** Test and change settings. */
    canWrite: boolean;
    /** Connect, finish setup and remove (these also create or archive a tool). */
    canInstall: boolean;
    /** Open the agent tool (the tools screen needs agents:write). */
    canOpenTool: boolean;
}

interface ConnectionCardProps {
    connection: IntegrationConnectionResponse;
    provider: IntegrationProvider | undefined;
    /** The provider has settings to edit. */
    hasSettings: boolean;
    permissions: ConnectionPermissions;
    busy: ConnectionAction | null;
    onAction: (action: ConnectionAction) => void;
}

export function ConnectionCard({ connection, provider, hasSettings, permissions, busy, onAction }: ConnectionCardProps) {
    const state = connectionState(connection);
    const pill = STATE_PILL[state];
    const title = provider?.title ?? connection.provider;
    const toolUuid = permissions.canOpenTool ? connection.tool_uuids?.[0] : undefined;
    const disabled = busy !== null;
    const canSync = provider?.capabilities?.includes("sync") ?? false;
    const syncing = isSyncing(connection.sync);
    const itemLabel = provider?.sync_item_label ?? "items";
    const spinner = (action: ConnectionAction) =>
        busy === action ? <Loader2 className="animate-spin" aria-hidden /> : null;

    return (
        <Panel padding="sm" accent={state === "error" ? "danger" : "none"} className="grid gap-3">
            <div className="flex flex-wrap items-start gap-3">
                <ProviderIcon icon={provider?.icon} className="size-9" />
                <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <h3 className="font-semibold">{title}</h3>
                        <StatusPill tone={pill.tone} dot={state === "active"}>
                            {pill.label}
                        </StatusPill>
                    </div>
                    <p className="mt-0.5 truncate text-sm text-ink-2">
                        {connection.account_label ? (
                            <>
                                Connected as <span className="font-medium text-foreground">{connection.account_label}</span>
                            </>
                        ) : (
                            "No account name"
                        )}
                        <span className="text-ink-3"> · {authModeLabel(connection.auth_mode)}</span>
                    </p>
                </div>
                {toolUuid && (
                    <Button asChild variant="link" size="sm" className="h-auto px-0">
                        <Link href={`/tools/${toolUuid}`}>
                            <Wrench aria-hidden />
                            Agent tool
                            <ArrowUpRight aria-hidden />
                        </Link>
                    </Button>
                )}
            </div>

            {state === "error" && (
                <p className="text-sm text-danger">
                    {connectionErrorMessage(connection)}
                </p>
            )}
            {state === "pending" && (
                <p className="text-sm text-ink-2">
                    Sign-in finished but wasn&apos;t confirmed. Finish setup in the browser you signed in with, or remove
                    it and connect again.
                </p>
            )}
            {canSync && state !== "revoked" && state !== "pending" && (
                <p
                    className={`flex items-center gap-1.5 text-sm ${connection.sync?.status === "failed" ? "text-danger" : "text-ink-2"}`}
                    role="status"
                    aria-live="polite"
                >
                    {syncing && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
                    {syncSummary(connection.sync, itemLabel)}
                </p>
            )}
            {state === "not_installed" && (
                <p className="text-sm text-ink-2">The agent tool for this connection wasn&apos;t created yet.</p>
            )}

            {(permissions.canWrite || permissions.canInstall) && state !== "revoked" && (
                <div className="flex flex-wrap gap-2">
                    {permissions.canInstall && state === "error" && (
                        <Button
                            size="sm"
                            // Only reconnecting helps when the provider flagged the grant; otherwise a test may.
                            variant={needsReconnect(connection) ? "default" : "soft"}
                            onClick={() => onAction("reconnect")}
                            disabled={disabled}
                        >
                            <RefreshCw aria-hidden />
                            Reconnect
                        </Button>
                    )}
                    {permissions.canInstall && (state === "pending" || state === "not_installed") && (
                        <Button size="sm" onClick={() => onAction("finish")} disabled={disabled}>
                            {spinner("finish") ?? <PlugZap aria-hidden />}
                            Finish setup
                        </Button>
                    )}
                    {permissions.canWrite && canSync && state !== "pending" && (
                        <Button
                            size="sm"
                            variant={connection.sync ? "soft" : "default"}
                            onClick={() => onAction("sync")}
                            disabled={disabled || syncing}
                        >
                            {busy === "sync" || syncing ? (
                                <Loader2 className="animate-spin" aria-hidden />
                            ) : (
                                <CloudDownload aria-hidden />
                            )}
                            {syncing ? "Syncing…" : "Sync catalogue"}
                        </Button>
                    )}
                    {permissions.canWrite && state !== "pending" && (
                        <Button size="sm" variant="soft" onClick={() => onAction("test")} disabled={disabled}>
                            {spinner("test") ?? <PlugZap aria-hidden />}
                            Test
                        </Button>
                    )}
                    {permissions.canWrite && hasSettings && state !== "pending" && (
                        <Button size="sm" variant="soft" onClick={() => onAction("configure")} disabled={disabled}>
                            <Settings2 aria-hidden />
                            Settings
                        </Button>
                    )}
                    {permissions.canInstall && (
                        <AlertDialog>
                            <AlertDialogTrigger asChild>
                                <Button
                                    size="sm"
                                    variant="ghost"
                                    className="text-destructive hover:text-destructive sm:ml-auto"
                                    disabled={disabled}
                                >
                                    {spinner("remove") ?? <Trash2 aria-hidden />}
                                    Remove
                                </Button>
                            </AlertDialogTrigger>
                            <AlertDialogContent>
                                <AlertDialogHeader>
                                    <AlertDialogTitle>Remove this {title} connection?</AlertDialogTitle>
                                    <AlertDialogDescription>
                                        Its agent tool is archived and agents using it lose access straight away.
                                        You can connect again at any time.
                                    </AlertDialogDescription>
                                </AlertDialogHeader>
                                <AlertDialogFooter>
                                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                                    <AlertDialogAction
                                        className="bg-destructive text-white hover:bg-destructive/90"
                                        onClick={() => onAction("remove")}
                                    >
                                        Remove
                                    </AlertDialogAction>
                                </AlertDialogFooter>
                            </AlertDialogContent>
                        </AlertDialog>
                    )}
                </div>
            )}
        </Panel>
    );
}
