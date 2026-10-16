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

const LINK_CLASS = "text-primary underline-offset-4 hover:underline";

/** Shown after a password signup (or an unverified login) until the user
 *  enters the 6-digit code we emailed them. A link to the page this is shown
 *  on would not leave it, so the hosting form passes a callback instead:
 *  ``onSignIn`` from the login form, ``onStartOver`` from the signup form. */
export function CheckInbox({
  email,
  nextPath = null,
  onSignIn,
  onStartOver,
}: {
  email: string;
  nextPath?: string | null;
  onSignIn?: () => void;
  onStartOver?: () => void;
}) {
  const [code, setCode] = useState("");
  const [verifying, setVerifying] = useState(false);
  // Verified, but starting the session failed: the code is used up.
  const [spent, setSpent] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const verify = async (e: React.FormEvent) => {
    e.preventDefault();
    if (code.length !== CODE_LENGTH) return;
    setVerifying(true);
    setError(null);
    let verified = false;
    try {
      const res = await verifyEmailCodeApiV1AuthVerifyEmailCodePost({ body: { email, code } });
      if (res.error || !res.data) {
        setError(detailFromError(res.error, "Could not verify the code. Please try again."));
        setVerifying(false);
        return;
      }
      verified = true;
      // Stays "Verifying..." while the browser navigates away, so the used
      // code can't be submitted twice.
      await startLocalSession(res.data, nextPath);
    } catch {
      // Once verified the code is spent; the password still signs them in.
      if (verified) {
        setSpent(true);
        setError("Your email is verified, but we couldn't sign you in. Please sign in.");
      } else {
        setError("An error occurred. Please try again.");
      }
      setVerifying(false);
    }
  };

  const resend = async () => {
    setSending(true);
    try {
      const res = await resendVerificationApiV1AuthResendVerificationPost({ body: { email } });
      if (res.error) {
        toast.error(detailFromError(res.error, "Could not send a new code. Please try again."));
        return;
      }
      setError(null);
      // The API answers the same whether or not it sent (repeat requests are
      // dropped silently), so don't promise an email or clear a working code.
      toast.success("If a new code is due, it's on its way. Use the code from the newest email.");
    } catch {
      toast.error("Could not send a new code. Please try again.");
    } finally {
      setSending(false);
    }
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
        <Button type="submit" className="w-full" disabled={verifying || spent || code.length !== CODE_LENGTH}>
          {verifying ? "Verifying..." : "Verify email"}
        </Button>
      </form>
      <Button variant="outline" className="w-full" onClick={resend} disabled={sending}>
        {sending ? "Sending..." : "Send a new code"}
      </Button>
      <p className="text-sm text-muted-foreground">
        Wrong address?{" "}
        {onStartOver ? (
          <button type="button" onClick={onStartOver} className={LINK_CLASS}>
            Start over
          </button>
        ) : (
          <Link href="/auth/signup" className={LINK_CLASS}>
            Start over
          </Link>
        )}{" "}
        or{" "}
        {onSignIn ? (
          <button type="button" onClick={onSignIn} className={LINK_CLASS}>
            sign in
          </button>
        ) : (
          <Link href="/auth/login" className={LINK_CLASS}>
            sign in
          </Link>
        )}
      </p>
    </div>
  );
}
