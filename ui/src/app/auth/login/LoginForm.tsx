"use client";

import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { loginApiV1AuthLoginPost } from "@/client/sdk.gen";
import { CheckInbox } from "@/components/auth/CheckInbox";
import { AuthDivider, GoogleSignInButton } from "@/components/auth/GoogleSignInButton";
import { LocalAuthShell } from "@/components/auth/LocalAuthShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { detailFromError, errorCodeFromError } from "@/lib/apiError";
import { startLocalSession } from "@/lib/auth/localSession";

export function LoginForm({
  signupEnabled,
  googleAuthEnabled,
  nextPath,
}: {
  signupEnabled: boolean;
  googleAuthEnabled: boolean;
  /** Same-origin path to continue to after signing in. */
  nextPath: string | null;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [unverifiedEmail, setUnverifiedEmail] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      const res = await loginApiV1AuthLoginPost({
        body: { email, password },
      });

      if (res.error || !res.data) {
        if (errorCodeFromError(res.error) === "email_not_verified") {
          setUnverifiedEmail(email);
          return;
        }
        toast.error(detailFromError(res.error, "Login failed"));
        return;
      }

      await startLocalSession(res.data, nextPath);
    } catch {
      toast.error("An error occurred. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  if (unverifiedEmail) {
    return (
      <LocalAuthShell>
        <CheckInbox email={unverifiedEmail} />
      </LocalAuthShell>
    );
  }

  return (
    <LocalAuthShell>
      <div className="space-y-1.5 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
        <p className="text-sm text-muted-foreground">
          Enter your email and password to continue
        </p>
      </div>

      {googleAuthEnabled && (
        <>
          <GoogleSignInButton nextPath={nextPath} />
          <AuthDivider />
        </>
      )}

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
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="password">Password</Label>
            <Link
              href="/auth/forgot-password"
              className="text-xs text-muted-foreground underline-offset-4 hover:text-primary hover:underline"
            >
              Forgot password?
            </Link>
          </div>
          <Input
            id="password"
            type="password"
            placeholder="Enter your password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? "Signing in..." : "Sign in"}
        </Button>
      </form>

      {signupEnabled && (
        <p className="text-center text-sm text-muted-foreground">
          Don&apos;t have an account?{" "}
          <Link href="/auth/signup" className="text-primary underline-offset-4 hover:underline">
            Sign up
          </Link>
        </p>
      )}
    </LocalAuthShell>
  );
}
