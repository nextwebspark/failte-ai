"use client";

import { CheckCircle2, Loader2, Upload } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { installIntegrationApiV1IntegrationsConnectionsPost } from "@/client/sdk.gen";
import type { IntegrationConnectionResponse, IntegrationProvider } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { DialogFooter } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

import { ConfigSchemaForm } from "./ConfigSchemaForm";
import { integrationErrorMessage } from "./messages";
import { fieldsFromSchema, type FormErrors, type FormValues, initialValues, valuesToConfig } from "./schemaForm";
import { MAX_KEY_BYTES, parseServiceAccountKey } from "./serviceAccount";

interface ServiceAccountConnectProps {
    provider: IntegrationProvider;
    onCancel: () => void;
    onInstalled: (connection: IntegrationConnectionResponse) => void;
}

/** Connect with a service-account JSON key plus the provider's settings. */
export function ServiceAccountConnect({ provider, onCancel, onInstalled }: ServiceAccountConnectProps) {
    const fields = useMemo(() => fieldsFromSchema(provider.config_schema), [provider]);
    // The key text lives only in this component's state; it is never logged.
    const [keyText, setKeyText] = useState("");
    const [fileName, setFileName] = useState<string | null>(null);
    const [values, setValues] = useState<FormValues>(() => initialValues(fields));
    const [errors, setErrors] = useState<FormErrors>({});
    const [keyTouched, setKeyTouched] = useState(false);
    const [installing, setInstalling] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const [fileError, setFileError] = useState<string | null>(null);

    const parsed = useMemo(() => parseServiceAccountKey(keyText), [keyText]);
    // One message at a time: a file problem replaces the parse error.
    const keyError = fileError ?? (keyTouched && !parsed.ok ? parsed.error : null);

    const readFile = async (file: File | undefined) => {
        if (!file) return;
        setFileName(file.name);
        setKeyText("");
        if (file.size > MAX_KEY_BYTES) {
            setFileError("That file is too large to be a key.");
            return;
        }
        try {
            setKeyText(await file.text());
            setFileError(null);
            setKeyTouched(true);
        } catch {
            setFileError("Couldn't read that file.");
        }
    };

    const install = async () => {
        setKeyTouched(true);
        const { config, errors: nextErrors } = valuesToConfig(fields, values);
        setErrors(nextErrors);
        if (fileError || !parsed.ok || Object.keys(nextErrors).length > 0) return;
        setInstalling(true);
        setFormError(null);
        try {
            const response = await installIntegrationApiV1IntegrationsConnectionsPost({
                body: {
                    provider: provider.id,
                    auth_mode: "service_account",
                    secret: parsed.key,
                    account_label: parsed.clientEmail,
                    config,
                },
            });
            if (response.error || !response.data) {
                setFormError(integrationErrorMessage(response.error, "Couldn't connect with this key"));
                return;
            }
            setKeyText("");
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
            <div className="grid gap-2">
                <Label htmlFor="sa-key">Service account key (JSON)</Label>
                <p className="text-xs text-muted-foreground">
                    In Google Cloud, open IAM &amp; Admin → Service accounts, choose an account, then Keys → Add key → JSON.
                    Upload the downloaded file or paste its contents.
                </p>
                <div className="flex flex-wrap items-center gap-3">
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept="application/json,.json"
                        className="hidden"
                        onChange={(e) => {
                            void readFile(e.target.files?.[0]);
                            e.target.value = "";
                        }}
                    />
                    <Button type="button" variant="soft" size="sm" onClick={() => fileInputRef.current?.click()}>
                        <Upload aria-hidden />
                        Upload key file
                    </Button>
                    {fileName && <span className="truncate text-sm text-ink-2">{fileName}</span>}
                </div>
                <Textarea
                    id="sa-key"
                    value={keyText}
                    onChange={(e) => {
                        setKeyText(e.target.value);
                        setFileName(null);
                        setFileError(null);
                    }}
                    onBlur={() => setKeyTouched(true)}
                    placeholder='{"type": "service_account", "client_email": "…", "private_key": "…"}'
                    className="h-28 font-mono text-xs"
                    spellCheck={false}
                    autoComplete="off"
                    aria-invalid={keyError !== null}
                    aria-describedby={keyError ? "sa-key-error" : parsed.ok ? "sa-key-ok" : undefined}
                    disabled={installing}
                />
                {keyError ? (
                    <p id="sa-key-error" className="text-xs text-destructive" role="alert">
                        {keyError}
                    </p>
                ) : (
                    parsed.ok && (
                        <p id="sa-key-ok" className="flex items-start gap-1.5 text-xs text-ok">
                            <CheckCircle2 className="mt-px size-3.5 shrink-0" aria-hidden />
                            <span>
                                Key for <span className="font-mono">{parsed.clientEmail}</span>. Share the Google
                                resources your agents need (for example the calendar) with this address.
                            </span>
                        </p>
                    )
                )}
            </div>

            {fields.length > 0 && (
                <div className="grid gap-3">
                    <h3 className="text-sm font-semibold">Settings</h3>
                    <ConfigSchemaForm
                        fields={fields}
                        values={values}
                        errors={errors}
                        onChange={(key, value) => setValues((v) => ({ ...v, [key]: value }))}
                        disabled={installing}
                        idPrefix="sa-cfg"
                    />
                </div>
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
