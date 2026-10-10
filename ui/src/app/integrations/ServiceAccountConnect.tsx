"use client";

import { CheckCircle2, Loader2, Upload } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { installIntegrationApiV1IntegrationsConnectionsPost } from "@/client/sdk.gen";
import type { IntegrationConnectionResponse, IntegrationProvider } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { DialogFooter } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Panel } from "@/components/ui/panel";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Textarea } from "@/components/ui/textarea";

import { ConfigSchemaForm } from "./ConfigSchemaForm";
import { integrationErrorMessage } from "./messages";
import { fieldsFromSchema, type FormErrors, type FormValues, initialValues, valuesToConfig } from "./schemaForm";
import { MAX_KEY_BYTES, parseServiceAccountKey } from "./serviceAccount";

/** A same-family service-account connection whose key can be reused. */
export interface ReusableKey {
    connectionId: string;
    /** The service account's email. */
    label: string;
}

const NEW_KEY = "__new__";

interface ServiceAccountConnectProps {
    provider: IntegrationProvider;
    /** Service accounts already connected for this provider's family. */
    reusable?: ReusableKey[];
    /** Start on "Use a different key" (e.g. when reconnecting). */
    preferNewKey?: boolean;
    onCancel: () => void;
    onInstalled: (connection: IntegrationConnectionResponse) => void;
}

/**
 * Connect with a service-account JSON key plus the provider's settings. When
 * the workspace already connected a service account for another provider of
 * the same family, reusing it is the default: the key is copied server-side
 * and never reaches the browser.
 */
export function ServiceAccountConnect({
    provider,
    reusable = [],
    preferNewKey = false,
    onCancel,
    onInstalled,
}: ServiceAccountConnectProps) {
    const [chosenSource, setKeySource] = useState<string>(() =>
        preferNewKey ? NEW_KEY : (reusable[0]?.connectionId ?? NEW_KEY),
    );
    // A connection that went away (removed, failed) since the choice was made
    // falls back to a new key.
    const reusing = reusable.find((r) => r.connectionId === chosenSource) ?? null;
    const keySource = reusing ? chosenSource : NEW_KEY;
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
        const { config, errors: nextErrors } = valuesToConfig(fields, values);
        setErrors(nextErrors);
        if (!reusing) {
            setKeyTouched(true);
            if (fileError || !parsed.ok) return;
        }
        if (Object.keys(nextErrors).length > 0) return;
        setInstalling(true);
        setFormError(null);
        try {
            const response = await installIntegrationApiV1IntegrationsConnectionsPost({
                body: reusing
                    ? {
                          provider: provider.id,
                          auth_mode: "service_account",
                          reuse_secret_from: reusing.connectionId,
                          account_label: reusing.label,
                          config,
                      }
                    : {
                          provider: provider.id,
                          auth_mode: "service_account",
                          secret: parsed.ok ? parsed.key : {},
                          account_label: parsed.ok ? parsed.clientEmail : undefined,
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
            {reusable.length > 0 && (
                <div className="grid gap-2">
                    <span id="sa-source-label" className="text-sm font-medium">
                        Service account
                    </span>
                    <RadioGroup
                        value={keySource}
                        onValueChange={(v) => setKeySource(v)}
                        aria-labelledby="sa-source-label"
                        className="gap-2"
                        disabled={installing}
                    >
                        {reusable.map((r) => (
                            <div key={r.connectionId} className="flex items-center gap-2">
                                <RadioGroupItem value={r.connectionId} id={`sa-reuse-${r.connectionId}`} />
                                <Label htmlFor={`sa-reuse-${r.connectionId}`} className="font-normal">
                                    Use the same service account (<span className="font-mono text-xs">{r.label}</span>)
                                </Label>
                            </div>
                        ))}
                        <div className="flex items-center gap-2">
                            <RadioGroupItem value={NEW_KEY} id="sa-reuse-new" />
                            <Label htmlFor="sa-reuse-new" className="font-normal">
                                Use a different key
                            </Label>
                        </div>
                    </RadioGroup>
                    {reusing && (
                        <Panel accent="sky" padding="sm">
                            <p className="text-sm">
                                Share {provider.share_hint ?? "what this integration needs"} with{" "}
                                <span className="font-mono text-xs">{reusing.label}</span>, the same as before.
                            </p>
                        </Panel>
                    )}
                </div>
            )}

            {!reusing && (
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
            )}

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
