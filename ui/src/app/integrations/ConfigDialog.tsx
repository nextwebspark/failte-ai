"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { updateConnectionConfigApiV1IntegrationsConnectionsConnectionIdPatch } from "@/client/sdk.gen";
import type { IntegrationConnectionResponse, IntegrationProvider } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";

import { ConfigSchemaForm } from "./ConfigSchemaForm";
import { integrationErrorMessage } from "./messages";
import { fieldsFromSchema, type FormErrors, type FormValues, initialValues, valuesToConfig } from "./schemaForm";

interface ConfigDialogProps {
    connection: IntegrationConnectionResponse | null;
    provider: IntegrationProvider | undefined;
    onOpenChange: (open: boolean) => void;
    onSaved: (connection: IntegrationConnectionResponse) => void;
    /** Shown after a fresh connect: the copy invites a review rather than an edit. */
    justConnected?: boolean;
}

/** Edit a connection's settings (PATCH merges the given keys). */
export function ConfigDialog({ connection, provider, onOpenChange, onSaved, justConnected = false }: ConfigDialogProps) {
    const fields = useMemo(() => fieldsFromSchema(provider?.config_schema), [provider]);
    const [values, setValues] = useState<FormValues>({});
    const [errors, setErrors] = useState<FormErrors>({});
    const [saving, setSaving] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);

    useEffect(() => {
        if (!connection) return;
        setValues(initialValues(fields, connection.config));
        setErrors({});
        setFormError(null);
    }, [connection, fields]);

    const save = async () => {
        if (!connection) return;
        const { config, errors: nextErrors } = valuesToConfig(fields, values);
        setErrors(nextErrors);
        if (Object.keys(nextErrors).length > 0) return;
        setSaving(true);
        setFormError(null);
        try {
            const response = await updateConnectionConfigApiV1IntegrationsConnectionsConnectionIdPatch({
                path: { connection_id: connection.id },
                body: { config },
            });
            if (response.error || !response.data) {
                setFormError(integrationErrorMessage(response.error, "Couldn't save the settings"));
                return;
            }
            toast.success("Settings saved");
            onSaved(response.data);
            onOpenChange(false);
        } catch {
            setFormError("Couldn't reach the server. Please try again.");
        } finally {
            setSaving(false);
        }
    };

    const title = provider?.title ?? connection?.provider ?? "Integration";

    return (
        <Dialog open={connection !== null} onOpenChange={(open) => !saving && onOpenChange(open)}>
            <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
                <DialogHeader>
                    <DialogTitle>{justConnected ? `Review ${title} settings` : `${title} settings`}</DialogTitle>
                    <DialogDescription>
                        {justConnected
                            ? "Connected. Check these settings before your agents use it — you can change them later."
                            : "How your agents use this connection."}
                    </DialogDescription>
                </DialogHeader>
                <form
                    id="integration-config-form"
                    onSubmit={(e) => {
                        e.preventDefault();
                        void save();
                    }}
                    noValidate
                >
                    {fields.length > 0 ? (
                        <ConfigSchemaForm
                            fields={fields}
                            values={values}
                            errors={errors}
                            onChange={(key, value) => setValues((v) => ({ ...v, [key]: value }))}
                            disabled={saving}
                            idPrefix="edit-cfg"
                        />
                    ) : (
                        <p className="text-sm text-muted-foreground">This integration has no settings.</p>
                    )}
                </form>
                {formError && (
                    <p className="text-sm text-destructive" role="alert">
                        {formError}
                    </p>
                )}
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
                        {justConnected ? "Skip" : "Cancel"}
                    </Button>
                    {fields.length > 0 && (
                        <Button type="submit" form="integration-config-form" disabled={saving}>
                            {saving && <Loader2 className="animate-spin" aria-hidden />}
                            Save settings
                        </Button>
                    )}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
