"use client";

import { RefreshCw, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  resendInvitationApiV1OrganizationsInvitationsInvitationIdResendPost,
  revokeInvitationApiV1OrganizationsInvitationsInvitationIdDelete,
} from "@/client/sdk.gen";
import type { InvitationResponse } from "@/client/types.gen";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useOrganizationTimezone } from "@/hooks/useOrganizationTimezone";
import { detailFromError } from "@/lib/apiError";
import { formatDate } from "@/lib/dateTime";

import { InviteLinkNotice } from "./InviteLinkNotice";
import { RoleBadge } from "./RoleBadge";

export function InvitationsCard({
  invitations,
  onChanged,
}: {
  invitations: InvitationResponse[];
  onChanged: () => void;
}) {
  const timezone = useOrganizationTimezone();
  const [fallbackLink, setFallbackLink] = useState<string | null>(null);

  const resend = async (invitation: InvitationResponse) => {
    const res = await resendInvitationApiV1OrganizationsInvitationsInvitationIdResendPost({
      path: { invitation_id: invitation.id },
    });
    if (res.error || !res.data) {
      toast.error(detailFromError(res.error, "Could not resend the invitation"));
      return;
    }
    if (res.data.email_sent) {
      toast.success(`Invitation re-sent to ${invitation.email}`);
      setFallbackLink(null);
    } else if (res.data.accept_url) {
      setFallbackLink(res.data.accept_url);
    }
    onChanged();
  };

  const revoke = async (invitation: InvitationResponse) => {
    const res = await revokeInvitationApiV1OrganizationsInvitationsInvitationIdDelete({
      path: { invitation_id: invitation.id },
    });
    if (res.error) {
      toast.error(detailFromError(res.error, "Could not revoke the invitation"));
      return;
    }
    toast.success(`Invitation to ${invitation.email} revoked`);
    onChanged();
  };

  if (invitations.length === 0 && !fallbackLink) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Pending invitations</CardTitle>
        <CardDescription>Invitations that haven&apos;t been accepted yet.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {fallbackLink && <InviteLinkNotice url={fallbackLink} />}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead className="hidden md:table-cell">Expires</TableHead>
              <TableHead className="w-24" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {invitations.map((invitation) => (
              <TableRow key={invitation.id}>
                <TableCell className="font-medium">{invitation.email}</TableCell>
                <TableCell>
                  <RoleBadge role={invitation.role} />
                </TableCell>
                <TableCell className="hidden text-sm text-muted-foreground md:table-cell">
                  {formatDate(invitation.expires_at, timezone)}
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Resend invitation to ${invitation.email}`}
                      onClick={() => void resend(invitation)}
                    >
                      <RefreshCw className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Revoke invitation to ${invitation.email}`}
                      onClick={() => void revoke(invitation)}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
