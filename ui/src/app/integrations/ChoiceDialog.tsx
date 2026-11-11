"use client";

import { Loader2, RotateCcw, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import {
    listConnectionChoicesApiV1IntegrationsConnectionsConnectionIdChoicesGet,
    updateConnectionConfigApiV1IntegrationsConnectionsConnectionIdPatch,
} from "@/client/sdk.gen";
import type { IntegrationChoice, IntegrationConnectionResponse, IntegrationProvider } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Skeleton } from "@/components/ui/skeleton";

import { CalendlyNotes } from "./CalendlyNotes";
import { choiceKeys } from "./choices";
import { CALENDLY_PROVIDER, integrationErrorMessage } from "./messages";

interface ChoiceDialogProps {
    connection: IntegrationConnectionResponse | null;
    provider: IntegrationProvider | undefined;
    onOpenChange: (open: boolean) => void;
    onSaved: (connection: IntegrationConnectionResponse) => void;
    /** Opened right after connecting: "Later" rather than "Cancel". */
    justConnected?: boolean;
}

/**
 * Pick one of the values the provider lists live, e.g. which Calendly event
 * callers book. Saving sends the choice's own config patch.
 */
export function ChoiceDialog({ connection, provider, onOpenChange, onSaved, justConnected = false }: ChoiceDialogProps) {
    const [saving, setSaving] = useState(false);
    return (
        <Dialog open={connection !== null} onOpenChange={(open) => !saving && onOpenChange(open)}>
            <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
                {connection && (
                    <ChoiceBody
                        key={connection.id}
                        connection={connection}
                        provider={provider}
                        justConnected={justConnected}
                        saving={saving}
                        setSaving={setSaving}
                        onClose={() => onOpenChange(false)}
                        onSaved={onSaved}
                    />
                )}
            </DialogContent>
        </Dialog>
    );
}

type Loaded = { state: "loading" } | { state: "error"; message: string } | { state: "ready"; choices: IntegrationChoice[] };

function ChoiceBody({
    connection,
    provider,
    justConnected,
    saving,
    setSaving,
    onClose,
    onSaved,
}: {
    connection: IntegrationConnectionResponse;
    provider: IntegrationProvider | undefined;
    justConnected: boolean;
    saving: boolean;
    setSaving: (saving: boolean) => void;
    onClose: () => void;
    onSaved: (connection: IntegrationConnectionResponse) => void;
}) {
    const calendly = connection.provider === CALENDLY_PROVIDER;
    const keys = choiceKeys(provider?.config_schema);
    const current = keys ? connection.config?.[keys.value] : undefined;
    const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
    const [picked, setPicked] = useState<string>(typeof current === "string" ? current : "");
    const [formError, setFormError] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoaded({ state: "loading" });
        try {
            const response = await listConnectionChoicesApiV1IntegrationsConnectionsConnectionIdChoicesGet({
                path: { connection_id: connection.id },
            });
            if (response.error || !response.data) {
                setLoaded({
                    state: "error",
                    message: integrationErrorMessage(response.error, "Couldn't read the list. Please try again."),
                });
                return;
            }
            setLoaded({ state: "ready", choices: response.data.choices });
        } catch {
            setLoaded({ state: "error", message: "Couldn't reach the server. Please try again." });
        }
    }, [connection.id]);

    useEffect(() => {
        void load();
    }, [load]);

    const choices = loaded.state === "ready" ? loaded.choices : [];
    const choice = choices.find((c) => c.value === picked) ?? null;

    const save = async () => {
        if (!choice) {
            setFormError(calendly ? "Pick the event callers should book." : "Pick one first.");
            return;
        }
        setSaving(true);
        setFormError(null);
        try {
            const response = await updateConnectionConfigApiV1IntegrationsConnectionsConnectionIdPatch({
                path: { connection_id: connection.id },
                body: { config: choice.config },
            });
            if (response.error || !response.data) {
                setFormError(integrationErrorMessage(response.error, "Couldn't save your choice"));
                return;
            }
            toast.success(calendly ? `Callers now book “${choice.label}”` : "Saved");
            onSaved(response.data);
            setSaving(false);
            onClose();
        } catch {
            setFormError("Couldn't reach the server. Please try again.");
        } finally {
            setSaving(false);
        }
    };

    return (
        <>
            <DialogHeader>
                <DialogTitle>{calendly ? "Which Calendly event should callers book?" : "Choose one"}</DialogTitle>
                <DialogDescription>
                    {calendly
                        ? "Your agent offers free times from this event and books callers into it. Your working hours, notice and limits come from Calendly."
                        : `Pick what ${provider?.title ?? "this connection"} should use.`}
                </DialogDescription>
            </DialogHeader>

            {loaded.state === "loading" && (
                <div className="grid gap-2" aria-busy="true" aria-label="Loading">
                    <Skeleton className="h-12 w-full rounded-lg" />
                    <Skeleton className="h-12 w-full rounded-lg" />
                </div>
            )}
            {loaded.state === "error" && (
                <div className="grid gap-3">
                    <p className="flex items-start gap-2 text-sm text-destructive" role="alert">
                        <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                        {loaded.message}
                    </p>
                    <Button variant="outline" size="sm" className="justify-self-start" onClick={() => void load()}>
                        <RotateCcw aria-hidden />
                        Try again
                    </Button>
                </div>
            )}
            {loaded.state === "ready" && choices.length === 0 && (
                <p className="text-sm text-ink-2">
                    {calendly
                        ? "There are no switched-on events in this Calendly account. Create or switch one on in Calendly, then try again."
                        : "There is nothing to choose from yet."}
                </p>
            )}
            {loaded.state === "ready" && choices.length > 0 && (
                <RadioGroup
                    value={picked}
                    onValueChange={(v) => {
                        setPicked(v);
                        setFormError(null);
                    }}
                    aria-label={calendly ? "Calendly events" : "Choices"}
                    className="gap-2"
                    disabled={saving}
                >
                    {choices.map((c, index) => {
                        const id = `choice-${index}`;
                        return (
                            <div key={c.value} className="flex items-start gap-2.5 rounded-lg border border-line p-3">
                                <RadioGroupItem value={c.value} id={id} className="mt-0.5" />
                                <div className="min-w-0">
                                    <Label htmlFor={id} className="font-medium">
                                        {c.label}
                                    </Label>
                                    {c.detail && <p className="text-xs text-ink-3">{c.detail}</p>}
                                    {c.warning && <p className="mt-1 text-xs text-amber">{c.warning}</p>}
                                </div>
                            </div>
                        );
                    })}
                </RadioGroup>
            )}

            {calendly && <CalendlyNotes />}

            {formError && (
                <p className="text-sm text-destructive" role="alert">
                    {formError}
                </p>
            )}
            <DialogFooter>
                <Button variant="outline" onClick={onClose} disabled={saving}>
                    {justConnected ? "Later" : "Cancel"}
                </Button>
                <Button onClick={() => void save()} disabled={saving || loaded.state !== "ready" || choices.length === 0}>
                    {saving && <Loader2 className="animate-spin" aria-hidden />}
                    Save
                </Button>
            </DialogFooter>
        </>
    );
}
