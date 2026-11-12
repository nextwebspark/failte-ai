"use client";

import { ExternalLink, Loader2 } from "lucide-react";
import { useState } from "react";

import { installIntegrationApiV1IntegrationsConnectionsPost } from "@/client/sdk.gen";
import type { IntegrationConnectionResponse, IntegrationProvider } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { CalendlyNotes } from "./CalendlyNotes";
import { CALENDLY_PROVIDER, integrationErrorMessage, scopeLabel } from "./messages";

interface TokenConnectProps {
    provider: IntegrationProvider;
    onCancel: () => void;
    onInstalled: (connection: IntegrationConnectionResponse) => void;
}

/** A token is one word of at least 20 characters (Calendly's are far longer). */
export function tokenProblem(token: string): string | null {
    const value = token.trim();
    if (!value) return "Paste your token.";
    if (/\s/.test(value)) return "A token has no spaces. Copy it again in one piece.";
    if (value.length < 20) return "That looks too short to be a token. Copy the whole token.";
    return null;
}

/**
 * Connect with a token the owner pastes (e.g. a Calendly personal access
 * token). The server checks it with the provider before saving it; the
 * token lives only in this form's state and is cleared once sent.
 */
export function TokenConnect({ provider, onCancel, onInstalled }: TokenConnectProps) {
    const [token, setToken] = useState("");
    const [touched, setTouched] = useState(false);
    const [installing, setInstalling] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);
    const calendly = provider.id === CALENDLY_PROVIDER;
    const problem = tokenProblem(token);
    const shownProblem = touched ? problem : null;

    const install = async () => {
        setTouched(true);
        if (problem) return;
        setInstalling(true);
        setFormError(null);
        try {
            const response = await installIntegrationApiV1IntegrationsConnectionsPost({
                body: { provider: provider.id, auth_mode: "api_key", secret: { token: token.trim() } },
            });
            if (response.error || !response.data) {
                setFormError(integrationErrorMessage(response.error, "Couldn't connect with this token"));
                return;
            }
            setToken("");
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
            {calendly && (
                <ol className="list-decimal space-y-1.5 pl-4 text-sm text-ink-2">
                    <li>
                        In Calendly, open your profile menu, then{" "}
                        <a
                            href="https://calendly.com/app/developer?tab=personal_access_tokens"
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-0.5 text-sky underline-offset-2 hover:underline"
                        >
                            Developer, then Personal access tokens
                            <ExternalLink className="size-3" aria-hidden />
                            <span className="sr-only">(opens in a new tab)</span>
                        </a>
                        . No Developer item? Use Integrations, then API and webhooks.
                    </li>
                    <li>
                        Create a token. When Calendly asks what it may do, tick:{" "}
                        {provider.scopes.map(scopeLabel).join(", ")}.
                    </li>
                    <li>Copy the token (Calendly shows it only once) and paste it here. We check it with Calendly before saving it.</li>
                </ol>
            )}

            <div className="grid gap-2">
                <Label htmlFor="token-input">{calendly ? "Personal access token" : "Token"}</Label>
                <Input
                    id="token-input"
                    type="password"
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    onBlur={() => setTouched(true)}
                    autoComplete="off"
                    spellCheck={false}
                    aria-invalid={shownProblem !== null}
                    aria-describedby={shownProblem ? "token-error" : "token-hint"}
                    disabled={installing}
                />
                {shownProblem ? (
                    <p id="token-error" className="text-xs text-destructive" role="alert">
                        {shownProblem}
                    </p>
                ) : (
                    <p id="token-hint" className="text-xs text-muted-foreground">
                        Stored encrypted. It is never shown again.
                    </p>
                )}
            </div>

            {calendly && <CalendlyNotes />}

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
                    {installing ? "Checking…" : "Connect"}
                </Button>
            </DialogFooter>
        </form>
    );
}
