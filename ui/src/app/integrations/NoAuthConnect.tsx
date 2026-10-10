"use client";

import { Loader2 } from "lucide-react";
import { useMemo, useState } from "react";

import { installIntegrationApiV1IntegrationsConnectionsPost } from "@/client/sdk.gen";
import type { IntegrationConnectionResponse, IntegrationProvider } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { DialogFooter } from "@/components/ui/dialog";

import { ConfigSchemaForm } from "./ConfigSchemaForm";
import { integrationErrorMessage } from "./messages";
import { fieldsFromSchema, type FormErrors, type FormValues, initialValues, valuesToConfig } from "./schemaForm";

interface NoAuthConnectProps {
    provider: IntegrationProvider;
    onCancel: () => void;
    onInstalled: (connection: IntegrationConnectionResponse) => void;
}

/** Connect a provider that reads public data: settings only, no sign-in or key. */
export function NoAuthConnect({ provider, onCancel, onInstalled }: NoAuthConnectProps) {
    const fields = useMemo(() => fieldsFromSchema(provider.config_schema), [provider]);
    const [values, setValues] = useState<FormValues>(() => initialValues(fields));
    const [errors, setErrors] = useState<FormErrors>({});
    const [installing, setInstalling] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);
    const syncs = provider.capabilities?.includes("sync") ?? false;

    const install = async () => {
        const { config, errors: nextErrors } = valuesToConfig(fields, values);
        setErrors(nextErrors);
        if (Object.keys(nextErrors).length > 0) return;
        setInstalling(true);
        setFormError(null);
        try {
            const response = await installIntegrationApiV1IntegrationsConnectionsPost({
                body: { provider: provider.id, auth_mode: "none", config },
            });
            if (response.error || !response.data) {
                setFormError(integrationErrorMessage(response.error, "Couldn't connect"));
                return;
            }
            onInstalled(response.data);
        } catch {
            setFormError("Couldn't reach the server. Please try again.");
        } finally {
            setInstalling(false);
        }
    };

    return (
        <form
            className="grid gap-5"
            onSubmit={(e) => {
                e.preventDefault();
                void install();
            }}
            noValidate
        >
            <p className="text-sm text-ink-2">
                No sign-in is needed: this integration only reads public pages.
                {syncs && ` Once connected, its ${provider.sync_item_label ?? "data"} are imported in the background.`}
            </p>
            {fields.length > 0 && (
                <ConfigSchemaForm
                    fields={fields}
                    values={values}
                    errors={errors}
                    onChange={(key, value) => setValues((v) => ({ ...v, [key]: value }))}
                    disabled={installing}
                    idPrefix="none-cfg"
                />
            )}
            {formError && (
                <p className="text-sm text-destructive" role="alert">
                    {formError}
                </p>
            )}
            <DialogFooter>
                <Button type="button" variant="outline" onClick={onCancel} disabled={installing}>
                    Cancel
                </Button>
                <Button type="submit" disabled={installing}>
                    {installing && <Loader2 className="animate-spin" aria-hidden />}
                    Connect
                </Button>
            </DialogFooter>
        </form>
    );
}
