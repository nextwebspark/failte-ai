"use client";

import { MailCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { resendVerificationApiV1AuthResendVerificationPost } from "@/client/sdk.gen";
import { Button } from "@/components/ui/button";

/** Shown after a password signup (or an unverified login) until the user
 *  clicks the emailed verification link. */
export function CheckInbox({ email }: { email: string }) {
  const [sending, setSending] = useState(false);

  const resend = async () => {
    setSending(true);
    const res = await resendVerificationApiV1AuthResendVerificationPost({ body: { email } });
    setSending(false);
    if (res.error) {
      toast.error("Could not resend the email. Please try again.");
      return;
    }
    toast.success("Verification email sent");
  };

  return (
    <div className="space-y-5 text-center">
      <MailCheck className="mx-auto size-10 text-primary" aria-hidden />
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight">Check your inbox</h1>
        <p className="text-sm text-muted-foreground">
          We sent a verification link to <span className="font-medium text-foreground">{email}</span>.
          Click it to finish setting up your account.
        </p>
      </div>
      <Button variant="outline" className="w-full" onClick={resend} disabled={sending}>
        {sending ? "Sending..." : "Resend email"}
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
