"use client";

import { useEffect, useRef, useState } from "react";

import { googleCallbackApiV1AuthGoogleCallbackPost } from "@/client/sdk.gen";
import { AuthStatus } from "@/components/auth/AuthStatus";
import { LocalAuthShell } from "@/components/auth/LocalAuthShell";
import { detailFromError } from "@/lib/apiError";
import { startLocalSession } from "@/lib/auth/localSession";

export function GoogleCallback({
  code,
  state,
  providerError,
}: {
  code: string | null;
  state: string | null;
  providerError: string | null;
}) {
  const [error, setError] = useState<string | null>(
    providerError === "access_denied"
      ? "Google sign-in was cancelled."
      : providerError || !code || !state
        ? "Google sign-in did not complete."
        : null,
  );
  // Authorization codes are single-use: guard against a double effect run.
  const started = useRef(false);

  useEffect(() => {
    if (!code || !state || providerError || started.current) return;
    started.current = true;
    (async () => {
      const res = await googleCallbackApiV1AuthGoogleCallbackPost({
        // Sends back the sign-in state cookie set by /auth/google/start.
        credentials: "include",
        body: { code, state },
      });
      if (res.error || !res.data) {
        setError(detailFromError(res.error, "Google sign-in failed."));
        return;
      }
      await startLocalSession(res.data, res.data.next_path);
    })().catch(() => setError("Google sign-in failed."));
  }, [code, state, providerError]);

  return (
    <LocalAuthShell>
      {error ? (
        <AuthStatus
          title="Couldn't sign you in"
          message={error}
          action={{ href: "/auth/login", label: "Back to sign in" }}
        />
      ) : (
        <AuthStatus title="Signing you in" message="One moment..." />
      )}
    </LocalAuthShell>
  );
}
