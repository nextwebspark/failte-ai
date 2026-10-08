"use client";

import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { forgotPasswordApiV1AuthForgotPasswordPost } from "@/client/sdk.gen";
import { AuthStatus } from "@/components/auth/AuthStatus";
import { LocalAuthShell } from "@/components/auth/LocalAuthShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    const res = await forgotPasswordApiV1AuthForgotPasswordPost({ body: { email } });
    setLoading(false);
    if (res.error) {
      toast.error("Something went wrong. Please try again.");
      return;
    }
    setSent(true);
  };

  return (
    <LocalAuthShell>
      {sent ? (
        <AuthStatus
          title="Check your inbox"
          message={`If an account exists for ${email}, we sent a link to reset its password.`}
          action={{ href: "/auth/login", label: "Back to sign in" }}
        />
      ) : (
        <>
          <div className="space-y-1.5 text-center">
            <h1 className="text-2xl font-semibold tracking-tight">Reset your password</h1>
            <p className="text-sm text-muted-foreground">
              Enter your email and we&apos;ll send you a reset link
            </p>
          </div>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Sending..." : "Send reset link"}
            </Button>
          </form>
          <p className="text-center text-sm text-muted-foreground">
            <Link href="/auth/login" className="text-primary underline-offset-4 hover:underline">
              Back to sign in
            </Link>
          </p>
        </>
      )}
    </LocalAuthShell>
  );
}
