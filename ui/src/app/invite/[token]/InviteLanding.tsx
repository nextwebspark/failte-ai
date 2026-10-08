"use client";

import { Users } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import {
  acceptInvitationApiV1InvitationsAcceptPost,
  previewInvitationApiV1InvitationsLookupGet,
  selectMyOrganizationApiV1OrganizationsOrganizationIdSelectPost,
} from "@/client/sdk.gen";
import type { InvitationPreviewResponse } from "@/client/types.gen";
import { AuthStatus } from "@/components/auth/AuthStatus";
import { LocalAuthShell } from "@/components/auth/LocalAuthShell";
import { Button } from "@/components/ui/button";
import { detailFromError } from "@/lib/apiError";
import type { LocalUser } from "@/lib/auth";
import { useAuth } from "@/lib/auth";
import { ROLE_DESCRIPTIONS, ROLE_LABELS } from "@/lib/auth/roles";

const UNUSABLE_COPY: Record<string, string> = {
  accepted: "This invitation has already been accepted.",
  revoked: "This invitation was withdrawn. Ask the person who invited you for a new one.",
  expired: "This invitation has expired. Ask the person who invited you for a new one.",
};

/**
 * Landing page for an emailed invitation. Signed-in users accept here;
 * everyone else signs up (email fixed to the invited address) or signs in,
 * which joins the organization automatically.
 */
export function InviteLanding({ token }: { token: string }) {
  const { user, loading: authLoading, isAuthenticated, provider } = useAuth();
  const [preview, setPreview] = useState<InvitationPreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [accepting, setAccepting] = useState(false);

  useEffect(() => {
    (async () => {
      const res = await previewInvitationApiV1InvitationsLookupGet({ query: { token } });
      if (res.error || !res.data) {
        setError(detailFromError(res.error, "This invitation link is not valid."));
        return;
      }
      setPreview(res.data);
    })().catch(() => setError("Could not load this invitation."));
  }, [token]);

  const openWorkspace = async (organizationId: number) => {
    setAccepting(true);
    if (provider === "local") {
      const res = await selectMyOrganizationApiV1OrganizationsOrganizationIdSelectPost({
        path: { organization_id: organizationId },
      });
      if (res.error) {
        setAccepting(false);
        toast.error(detailFromError(res.error, "Could not open the workspace"));
        return;
      }
    }
    window.location.href = "/after-sign-in";
  };

  const accept = async () => {
    setAccepting(true);
    const res = await acceptInvitationApiV1InvitationsAcceptPost({ body: { token } });
    if (res.error) {
      setAccepting(false);
      toast.error(detailFromError(res.error, "Could not accept the invitation"));
      return;
    }
    window.location.href = "/after-sign-in";
  };

  const signedInEmail =
    (user as LocalUser | null)?.email ??
    (user as { primaryEmail?: string | null } | null)?.primaryEmail ??
    null;
  const invitePath = `/invite/${encodeURIComponent(token)}`;

  let body: React.ReactNode;
  if (error) {
    body = (
      <AuthStatus
        title="Invitation not found"
        message={error}
        action={{ href: "/auth/login", label: "Go to sign in" }}
      />
    );
  } else if (!preview || authLoading) {
    body = <AuthStatus title="Loading invitation" message="One moment..." />;
  } else if (preview.status === "accepted" && isAuthenticated) {
    // Signing in already claims pending invitations for a verified address,
    // so arriving back here after login usually means "you're in".
    body = (
      <div className="space-y-5 text-center">
        <div className="space-y-1.5">
          <h1 className="text-2xl font-semibold tracking-tight">
            You&apos;re a member of {preview.organization_name}
          </h1>
          <p className="text-sm text-muted-foreground">Role: {ROLE_LABELS[preview.role]}</p>
        </div>
        <Button
          className="w-full"
          onClick={() => void openWorkspace(preview.organization_id)}
          disabled={accepting}
        >
          Open workspace
        </Button>
      </div>
    );
  } else if (preview.status !== "pending") {
    body = (
      <AuthStatus
        title="Invitation unavailable"
        message={UNUSABLE_COPY[preview.status] ?? "This invitation can no longer be used."}
        action={{ href: "/auth/login", label: "Go to sign in" }}
      />
    );
  } else {
    const wrongAccount =
      isAuthenticated && signedInEmail && signedInEmail.toLowerCase() !== preview.email;
    body = (
      <div className="space-y-6 text-center">
        <Users className="mx-auto h-10 w-10 text-primary" aria-hidden />
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">
            Join {preview.organization_name}
          </h1>
          <p className="text-sm text-muted-foreground">
            {preview.inviter_name ? `${preview.inviter_name} invited` : "You've been invited as"}{" "}
            {preview.inviter_name && "you as "}
            <span className="font-medium text-foreground">{ROLE_LABELS[preview.role]}</span>.{" "}
            {ROLE_DESCRIPTIONS[preview.role]}
          </p>
          <p className="text-xs text-muted-foreground">Invitation for {preview.email}</p>
        </div>

        {isAuthenticated && !wrongAccount ? (
          <Button className="w-full" onClick={() => void accept()} disabled={accepting}>
            {accepting ? "Joining..." : "Accept invitation"}
          </Button>
        ) : wrongAccount ? (
          <p className="rounded-md border border-amber/40 bg-amber-dim p-3 text-sm">
            You&apos;re signed in as {signedInEmail}. Sign out and sign in as {preview.email} to
            accept this invitation.
          </p>
        ) : (
          <div className="space-y-2">
            <Button asChild className="w-full">
              <Link
                href={`/auth/signup?invite=${encodeURIComponent(token)}&email=${encodeURIComponent(preview.email)}`}
              >
                Create your account
              </Link>
            </Button>
            <Button asChild variant="outline" className="w-full">
              <Link href={`/auth/login?next=${encodeURIComponent(invitePath)}`}>
                I already have an account
              </Link>
            </Button>
          </div>
        )}
      </div>
    );
  }

  return <LocalAuthShell>{body}</LocalAuthShell>;
}
