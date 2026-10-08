"use client";

import { useState } from "react";
import { toast } from "sonner";

import { googleStartApiV1AuthGoogleStartGet } from "@/client/sdk.gen";
import { Button } from "@/components/ui/button";
import { detailFromError } from "@/lib/apiError";

function GoogleMark() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="size-4">
      <path fill="#4285F4" d="M23.5 12.27c0-.85-.08-1.67-.22-2.45H12v4.64h6.45a5.52 5.52 0 0 1-2.4 3.62v3h3.88c2.27-2.09 3.57-5.17 3.57-8.81z" />
      <path fill="#34A853" d="M12 24c3.24 0 5.96-1.07 7.94-2.92l-3.88-3c-1.08.72-2.45 1.15-4.06 1.15-3.12 0-5.77-2.11-6.71-4.95H1.28v3.1A12 12 0 0 0 12 24z" />
      <path fill="#FBBC05" d="M5.29 14.28A7.2 7.2 0 0 1 4.91 12c0-.79.14-1.56.38-2.28v-3.1H1.28A12 12 0 0 0 0 12c0 1.94.46 3.77 1.28 5.38l4.01-3.1z" />
      <path fill="#EA4335" d="M12 4.77c1.76 0 3.34.61 4.59 1.8l3.44-3.44C17.95 1.19 15.24 0 12 0A12 12 0 0 0 1.28 6.62l4.01 3.1C6.23 6.88 8.88 4.77 12 4.77z" />
    </svg>
  );
}

export function GoogleSignInButton({
  inviteToken,
  nextPath,
  label = "Continue with Google",
}: {
  inviteToken?: string | null;
  nextPath?: string | null;
  label?: string;
}) {
  const [loading, setLoading] = useState(false);

  const start = async () => {
    setLoading(true);
    const res = await googleStartApiV1AuthGoogleStartGet({
      query: {
        invite_token: inviteToken ?? undefined,
        next: nextPath ?? undefined,
      },
    });
    if (res.error || !res.data) {
      toast.error(detailFromError(res.error, "Google sign-in is unavailable"));
      setLoading(false);
      return;
    }
    window.location.href = res.data.authorization_url;
  };

  return (
    <Button type="button" variant="outline" className="w-full gap-2" onClick={start} disabled={loading}>
      <GoogleMark />
      {loading ? "Redirecting..." : label}
    </Button>
  );
}

export function AuthDivider() {
  return (
    <div className="flex items-center gap-3 text-xs uppercase text-muted-foreground">
      <span className="h-px flex-1 bg-border" />
      or
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}
