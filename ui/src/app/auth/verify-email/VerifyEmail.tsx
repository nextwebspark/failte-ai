"use client";

import { useEffect, useRef, useState } from "react";

import { verifyEmailApiV1AuthVerifyEmailPost } from "@/client/sdk.gen";
import { AuthStatus } from "@/components/auth/AuthStatus";
import { LocalAuthShell } from "@/components/auth/LocalAuthShell";
import { detailFromError } from "@/lib/apiError";
import { startLocalSession } from "@/lib/auth/localSession";

export function VerifyEmail({ token }: { token: string | null }) {
  const [error, setError] = useState<string | null>(
    token ? null : "This verification link is incomplete.",
  );
  // The token is single-use: guard against React running the effect twice.
  const started = useRef(false);

  useEffect(() => {
    if (!token || started.current) return;
    started.current = true;
    (async () => {
      const res = await verifyEmailApiV1AuthVerifyEmailPost({ body: { token } });
      if (res.error || !res.data) {
        setError(detailFromError(res.error, "Could not verify your email."));
        return;
      }
      await startLocalSession(res.data);
    })().catch(() => setError("Could not verify your email."));
  }, [token]);

  return (
    <LocalAuthShell>
      {error ? (
        <AuthStatus
          title="Verification failed"
          message={`${error} Sign in to request a new link.`}
          action={{ href: "/auth/login", label: "Back to sign in" }}
        />
      ) : (
        <AuthStatus title="Verifying your email" message="One moment..." />
      )}
    </LocalAuthShell>
  );
}
