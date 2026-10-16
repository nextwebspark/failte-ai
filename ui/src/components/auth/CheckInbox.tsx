"use client";

import { MailCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import {
  resendVerificationApiV1AuthResendVerificationPost,
  verifyEmailCodeApiV1AuthVerifyEmailCodePost,
} from "@/client/sdk.gen";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { detailFromError } from "@/lib/apiError";
import { startLocalSession } from "@/lib/auth/localSession";

const CODE_LENGTH = 6;

/** Shown after a password signup (or an unverified login) until the user
 *  enters the 6-digit code we emailed them. */
export function CheckInbox({ email, nextPath = null }: { email: string; nextPath?: string | null }) {
  const [code, setCode] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const verify = async (e: React.FormEvent) => {
    e.preventDefault();
    if (code.length !== CODE_LENGTH) return;
    setVerifying(true);
    setError(null);
    try {
      const res = await verifyEmailCodeApiV1AuthVerifyEmailCodePost({ body: { email, code } });
      if (res.error || !res.data) {
        setError(detailFromError(res.error, "Could not verify the code. Please try again."));
        return;
      }
      await startLocalSession(res.data, nextPath);
    } catch {
      setError("An error occurred. Please try again.");
    } finally {
      setVerifying(false);
    }
  };

  const resend = async () => {
    setSending(true);
    const res = await resendVerificationApiV1AuthResendVerificationPost({ body: { email } });
    setSending(false);
    if (res.error) {
      toast.error(detailFromError(res.error, "Could not send a new code. Please try again."));
      return;
    }
    setCode("");
    setError(null);
    toast.success("We sent you a new code");
  };

  return (
    <div className="space-y-5 text-center">
      <MailCheck className="mx-auto size-10 text-primary" aria-hidden />
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Check your inbox</h1>
        <p className="text-sm text-muted-foreground">
          We sent a 6-digit code to <span className="font-medium text-foreground">{email}</span>.
          Enter it below to finish setting up your account.
        </p>
      </div>
      <form onSubmit={verify} className="space-y-3 text-left">
        <Label htmlFor="verification-code">Verification code</Label>
        <Input
          id="verification-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          placeholder="123456"
          className="text-center font-mono text-lg tracking-[0.5em]"
          value={code}
          // Pasted codes often carry spaces or dashes; keep the digits only.
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, CODE_LENGTH))}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "verification-code-error" : undefined}
          autoFocus
          required
        />
        {error && (
          <p id="verification-code-error" role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" className="w-full" disabled={verifying || code.length !== CODE_LENGTH}>
          {verifying ? "Verifying..." : "Verify email"}
        </Button>
      </form>
      <Button variant="outline" className="w-full" onClick={resend} disabled={sending}>
        {sending ? "Sending..." : "Send a new code"}
      </Button>
      <p className="text-sm text-muted-foreground">
        Wrong address?{" "}
        <Link href="/auth/signup" className="text-primary underline-offset-4 hover:underline">
          Start over
        </Link>
      </p>
    </div>
  );
}
