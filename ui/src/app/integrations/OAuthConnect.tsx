"use client";

import { Check, Copy, ExternalLink, Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { createProviderAppApiV1IntegrationsProviderAppsPost } from "@/client/sdk.gen";
import type { IntegrationProvider, ProviderAppResponse } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Panel } from "@/components/ui/panel";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { copyTextToClipboard } from "@/lib/clipboard";

import { credentialFamily, integrationErrorMessage, isUnavailableError, scopeLabel } from "./messages";
import { isTrustedAuthorizationUrl, startOAuth } from "./oauthCalls";
import { rememberPendingOAuth } from "./pendingOAuth";
import type { ReusableKey } from "./ServiceAccountConnect";

const NEW_CLIENT = "__new__";
const OTHER_ACCOUNT = "__other__";

function addingClientFor(selected: string): boolean {
    return selected === NEW_CLIENT;
}

interface OAuthConnectProps {
    provider: IntegrationProvider;
    providerApps: ProviderAppResponse[];
    /** Accounts already signed in for this provider's family (e.g. for Google Calendar). */
    knownAccounts?: ReusableKey[];
    /** The errored connection this sign-in replaces, if any. */
    replacesConnectionId?: string;
    onCancel: () => void;
    onProviderAppCreated: (app: ProviderAppResponse) => void;
}

/**
 * Bring-your-own OAuth: pick (or add) the workspace's OAuth client, choose any
 * optional permissions, then send the browser to the provider's sign-in page.
 * The provider redirects back to /integrations, which finishes the install.
 */
export function OAuthConnect({
    provider,
    providerApps,
    knownAccounts = [],
    replacesConnectionId,
    onCancel,
    onProviderAppCreated,
}: OAuthConnectProps) {
    // OAuth clients belong to the auth family: one saved for Google Calendar
    // serves Google Sheets too.
    const family = credentialFamily(provider);
    const apps = useMemo(
        () => providerApps.filter((a) => a.provider === family || a.provider === provider.id),
        [providerApps, family, provider.id],
    );
    const [selected, setSelected] = useState<string>(() => apps[0]?.id ?? NEW_CLIENT);
    // "Continue as alice@…": Google skips the account chooser and asks only for
    // this integration's new permissions. Each integration keeps its own grant.
    const [chosenAccount, setAccount] = useState<string>(() => knownAccounts[0]?.label ?? OTHER_ACCOUNT);
    // An account that is no longer offered falls back to "a different account".
    const account = knownAccounts.some((k) => k.label === chosenAccount) ? chosenAccount : OTHER_ACCOUNT;
    const loginHint = account === OTHER_ACCOUNT ? undefined : account;
    const sharedClient = !addingClientFor(selected) && apps.length > 0 && family !== provider.id;
    const [clientId, setClientId] = useState("");
    const [clientSecret, setClientSecret] = useState("");
    const [optionalScopes, setOptionalScopes] = useState<string[]>([]);
    const [busy, setBusy] = useState<"saving" | "redirecting" | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [copied, setCopied] = useState(false);

    useEffect(() => {
        // Coming back with the browser's Back button restores this page from the
        // back/forward cache with "Opening sign-in…" still showing: reset it.
        const onPageShow = (event: PageTransitionEvent) => {
            if (event.persisted) setBusy(null);
        };
        window.addEventListener("pageshow", onPageShow);
        return () => window.removeEventListener("pageshow", onPageShow);
    }, []);

    const redirectUri = provider.oauth?.redirect_uri ?? null;
    const addingClient = selected === NEW_CLIENT;

    if (!provider.oauth || !redirectUri) {
        return (
            <div className="grid gap-4">
                <Panel accent="amber" padding="sm">
                    <p className="text-sm">
                        Signing in with an account isn&apos;t set up on this server yet. Ask your administrator to
                        configure it, or connect with a service account key instead.
                    </p>
                </Panel>
                <DialogFooter>
                    <Button variant="outline" onClick={onCancel}>
                        Close
                    </Button>
                </DialogFooter>
            </div>
        );
    }

    const copyRedirect = async () => {
        try {
            await copyTextToClipboard(redirectUri);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 2000);
        } catch {
            setError("Couldn't copy. Select the address and copy it manually.");
        }
    };

    const saveClient = async (): Promise<string | null> => {
        if (!clientId.trim() || !clientSecret.trim()) {
            setError("Enter both the client ID and the client secret.");
            return null;
        }
        setBusy("saving");
        const response = await createProviderAppApiV1IntegrationsProviderAppsPost({
            body: { provider: provider.id, client_id: clientId.trim(), client_secret: clientSecret.trim() },
        });
        if (response.error || !response.data) {
            setError(integrationErrorMessage(response.error, "Couldn't save the OAuth client"));
            setBusy(null);
            return null;
        }
        setClientSecret("");
        onProviderAppCreated(response.data);
        return response.data.id;
    };

    const connect = async () => {
        setError(null);
        try {
            const appId = addingClient ? await saveClient() : selected;
            if (!appId) return;
            setSelected(appId);
            setBusy("redirecting");
            const response = await startOAuth({
                provider: provider.id,
                provider_app_id: appId,
                optional_scopes: optionalScopes,
                ...(loginHint ? { login_hint: loginHint } : {}),
            });
            if (response.error || !response.data) {
                setError(
                    isUnavailableError(response.error)
                        ? "Signing in with an account isn't set up on this server yet."
                        : integrationErrorMessage(response.error, "Couldn't start the sign-in"),
                );
                setBusy(null);
                return;
            }
            const { authorization_url: authorizationUrl, browser_nonce: nonce } = response.data;
            if (!isTrustedAuthorizationUrl(authorizationUrl)) {
                setError("The server returned an unexpected sign-in address, so it wasn't opened.");
                setBusy(null);
                return;
            }
            rememberPendingOAuth(provider.id, { nonce, replacesConnectionId });
            // Full-page redirect: the provider sends the browser back to /integrations.
            window.location.assign(authorizationUrl);
        } catch {
            setError("Couldn't reach the server. Please try again.");
            setBusy(null);
        }
    };

    const optional = provider.oauth.optional_scopes;

    return (
        <form
            className="grid gap-5"
            onSubmit={(e) => {
                e.preventDefault();
                void connect();
            }}
            noValidate
        >
            <div className="grid gap-2">
                <Label htmlFor="oauth-client">OAuth client</Label>
                <p className="text-xs text-muted-foreground">
                    Your own OAuth client from Google Cloud. Google shows its name on the sign-in screen.
                </p>
                <Select value={selected} onValueChange={(v) => {
                        // Radix's hidden native select can report "" while a just-saved
                        // client's option mounts: only a real switch counts.
                        if (!v || v === selected) return;
                        setSelected(v);
                        setError(null);
                    }} disabled={busy !== null}>
                    <SelectTrigger id="oauth-client" className="w-full">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        {apps.map((app) => (
                            <SelectItem key={app.id} value={app.id}>
                                <span className="truncate font-mono text-xs">{app.client_id}</span>
                            </SelectItem>
                        ))}
                        <SelectItem value={NEW_CLIENT}>Add a new OAuth client…</SelectItem>
                    </SelectContent>
                </Select>
            </div>

            {sharedClient && (
                <p className="text-xs text-muted-foreground">
                    This client is shared by your {family.charAt(0).toUpperCase() + family.slice(1)} integrations. Make sure this
                    address is also listed under its <strong>Authorized redirect URIs</strong>:{" "}
                    <code className="break-all font-mono" aria-label="Redirect URI">
                        {redirectUri}
                    </code>
                </p>
            )}

            {knownAccounts.length > 0 && (
                <div className="grid gap-2">
                    <span id="oauth-account-label" className="text-sm font-medium">
                        Account
                    </span>
                    <RadioGroup
                        value={account}
                        onValueChange={(v) => setAccount(v)}
                        aria-labelledby="oauth-account-label"
                        className="gap-2"
                        disabled={busy !== null}
                    >
                        {knownAccounts.map((known) => (
                            <div key={known.label} className="flex items-center gap-2">
                                <RadioGroupItem value={known.label} id={`oauth-as-${known.connectionId}`} />
                                <Label htmlFor={`oauth-as-${known.connectionId}`} className="font-normal">
                                    Continue as {known.label}
                                </Label>
                            </div>
                        ))}
                        <div className="flex items-center gap-2">
                            <RadioGroupItem value={OTHER_ACCOUNT} id="oauth-as-other" />
                            <Label htmlFor="oauth-as-other" className="font-normal">
                                Use a different account
                            </Label>
                        </div>
                    </RadioGroup>
                    {loginHint && (
                        <p className="text-xs text-muted-foreground">
                            Google will only ask to allow this integration&apos;s permissions.
                        </p>
                    )}
                </div>
            )}

            {addingClient && (
                <Panel padding="sm" className="grid gap-4">
                    <ol className="list-decimal space-y-1.5 pl-4 text-sm text-ink-2">
                        <li>
                            In the{" "}
                            <a
                                href="https://console.cloud.google.com/apis/credentials"
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-0.5 text-sky underline-offset-2 hover:underline"
                            >
                                Google Cloud console
                                <ExternalLink className="size-3" aria-hidden />
                                <span className="sr-only">(opens in a new tab)</span>
                            </a>
                            , create an OAuth client ID of type <strong>Web application</strong>.
                        </li>
                        <li>Add this exact address under <strong>Authorized redirect URIs</strong>:</li>
                    </ol>
                    <div className="flex items-center gap-2">
                        <code
                            className="min-w-0 flex-1 break-all rounded-md border border-line bg-panel px-2.5 py-1.5 font-mono text-xs"
                            aria-label="Redirect URI"
                        >
                            {redirectUri}
                        </code>
                        <Button
                            type="button"
                            variant="soft"
                            size="icon"
                            onClick={() => void copyRedirect()}
                            aria-label={copied ? "Copied" : "Copy redirect URI"}
                        >
                            {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
                        </Button>
                    </div>
                    <ol start={3} className="list-decimal space-y-1.5 pl-4 text-sm text-ink-2">
                        <li>Enable the {provider.title} API in the same project.</li>
                        <li>Paste the client ID and secret here.</li>
                    </ol>
                    <div className="grid gap-2">
                        <Label htmlFor="oauth-client-id">Client ID</Label>
                        <Input
                            id="oauth-client-id"
                            value={clientId}
                            onChange={(e) => setClientId(e.target.value)}
                            placeholder="1234-abc.apps.googleusercontent.com"
                            autoComplete="off"
                            spellCheck={false}
                            disabled={busy !== null}
                        />
                    </div>
                    <div className="grid gap-2">
                        <Label htmlFor="oauth-client-secret">Client secret</Label>
                        <Input
                            id="oauth-client-secret"
                            type="password"
                            value={clientSecret}
                            onChange={(e) => setClientSecret(e.target.value)}
                            autoComplete="new-password"
                            spellCheck={false}
                            disabled={busy !== null}
                        />
                        <p className="text-xs text-muted-foreground">Stored encrypted. It is never shown again.</p>
                    </div>
                </Panel>
            )}

            {optional.length > 0 && (
                <fieldset className="grid gap-2">
                    <legend className="mb-1 text-sm font-medium">Extra permissions (optional)</legend>
                    {optional.map((scope) => {
                        const id = `scope-${scope.replace(/[^a-z0-9]+/gi, "-")}`;
                        return (
                            <div key={scope} className="flex items-center gap-2">
                                <Checkbox
                                    id={id}
                                    checked={optionalScopes.includes(scope)}
                                    onCheckedChange={(checked) =>
                                        setOptionalScopes((current) =>
                                            checked === true ? [...current, scope] : current.filter((s) => s !== scope),
                                        )
                                    }
                                    disabled={busy !== null}
                                />
                                <Label htmlFor={id} className="font-normal">
                                    {scopeLabel(scope)}
                                </Label>
                            </div>
                        );
                    })}
                </fieldset>
            )}

            <div className="text-xs text-muted-foreground">
                <span className="font-medium text-ink-2">Always requested: </span>
                {provider.oauth.scopes.map(scopeLabel).join(" · ")}
            </div>

            {error && (
                <p className="text-sm text-destructive" role="alert">
                    {error}
                </p>
            )}

            <DialogFooter>
                <Button type="button" variant="outline" onClick={onCancel} disabled={busy !== null}>
                    Cancel
                </Button>
                <Button type="submit" disabled={busy !== null}>
                    {busy && <Loader2 className="animate-spin" aria-hidden />}
                    {busy === "redirecting" ? "Opening sign-in…" : addingClient ? "Save and sign in" : "Sign in"}
                </Button>
            </DialogFooter>
        </form>
    );
}
