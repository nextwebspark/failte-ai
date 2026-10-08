"use client";

import { useState } from "react";
import { toast } from "sonner";

import { resetPasswordApiV1AuthResetPasswordPost } from "@/client/sdk.gen";
import { AuthStatus } from "@/components/auth/AuthStatus";
import { LocalAuthShell } from "@/components/auth/LocalAuthShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { detailFromError } from "@/lib/apiError";
import { startLocalSession } from "@/lib/auth/localSession";

export function ResetPasswordForm({ token }: { token: string | null }) {
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(false);

  if (!token) {
    return (
      <LocalAuthShell>
        <AuthStatus
          title="Link incomplete"
          message="This password reset link is missing its token. Request a new one."
          action={{ href: "/auth/forgot-password", label: "Request a new link" }}
        />
      </LocalAuthShell>
    );
  }

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
      const res = await resetPasswordApiV1AuthResetPasswordPost({ body: { token, password } });
      if (res.error || !res.data) {
        toast.error(detailFromError(res.error, "Could not reset your password"));
        return;
      }
      await startLocalSession(res.data);
    } catch {
      toast.error("An error occurred. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <LocalAuthShell>
      <div className="space-y-1.5 text-center">
        <h1 className="text-2xl font-semibold tracking-tight">Choose a new password</h1>
        <p className="text-sm text-muted-foreground">You&apos;ll be signed in afterwards</p>
      </div>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="password">New password</Label>
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
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
            minLength={8}
          />
        </div>
        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? "Saving..." : "Set password"}
        </Button>
      </form>
    </LocalAuthShell>
  );
}
