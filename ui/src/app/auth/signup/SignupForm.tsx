"use client";

import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { signupApiV1AuthSignupPost } from "@/client/sdk.gen";
import { CheckInbox } from "@/components/auth/CheckInbox";
import { AuthDivider, GoogleSignInButton } from "@/components/auth/GoogleSignInButton";
import { LocalAuthShell } from "@/components/auth/LocalAuthShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { detailFromError } from "@/lib/apiError";
import { startLocalSession } from "@/lib/auth/localSession";

export function SignupForm({
  googleAuthEnabled,
  inviteToken,
  invitedEmail,
}: {
  googleAuthEnabled: boolean;
  // From an invitation link: join that organization; the email is fixed.
  inviteToken: string | null;
  invitedEmail: string | null;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState(invitedEmail ?? "");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [pendingVerification, setPendingVerification] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (password.length < 8) {
      toast.error("Password must be at least 8 characters");
      return;
    }

    if (password !== confirmPassword) {
      toast.error("Passwords do not match");
      return;
    }

    setLoading(true);

    try {
      const res = await signupApiV1AuthSignupPost({
        body: {
          email,
          password,
          name: name.trim() || null,
          invite_token: inviteToken,
        },
      });

      if (res.error || !res.data) {
        toast.error(detailFromError(res.error, "Signup failed"));
        return;
      }

      if (res.data.verification_required || !res.data.token) {
        setPendingVerification(email);
        return;
      }

      await startLocalSession({ token: res.data.token, user: res.data.user });
    } catch {
      toast.error("An error occurred. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  if (pendingVerification) {
    return (
      <LocalAuthShell>
        <CheckInbox email={pendingVerification} />
      </LocalAuthShell>
    );
  }

  return (
    <LocalAuthShell>
      <div className="space-y-1.5 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">
          {inviteToken ? "Join your team" : "Create an account"}
        </h1>
        <p className="text-sm text-muted-foreground">Enter your details to get started</p>
      </div>

      {googleAuthEnabled && (
        <>
          <GoogleSignInButton inviteToken={inviteToken} label="Sign up with Google" />
          <AuthDivider />
        </>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="name">Name</Label>
          <Input
            id="name"
            autoComplete="name"
            placeholder="Your name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            readOnly={Boolean(inviteToken && invitedEmail)}
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            placeholder="At least 8 characters"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="confirmPassword">Confirm password</Label>
          <Input
            id="confirmPassword"
            type="password"
            placeholder="Confirm your password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
            minLength={8}
          />
        </div>
        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? "Creating account..." : "Create account"}
        </Button>
      </form>

      <p className="text-center text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link href="/auth/login" className="text-primary underline-offset-4 hover:underline">
          Sign in
        </Link>
      </p>
    </LocalAuthShell>
  );
}
