"use client";

import { LogOut, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  leaveCurrentOrganizationApiV1OrganizationsLeavePost,
  removeMemberApiV1OrganizationsMembersUserIdDelete,
  updateMemberRoleApiV1OrganizationsMembersUserIdPatch,
} from "@/client/sdk.gen";
import type { MemberResponse } from "@/client/types.gen";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useOrganizationTimezone } from "@/hooks/useOrganizationTimezone";
import { detailFromError } from "@/lib/apiError";
import type { OrgRole } from "@/lib/auth/roles";
import { formatDate } from "@/lib/dateTime";

import { RoleBadge } from "./RoleBadge";
import { RoleSelect } from "./RoleSelect";

function displayName(member: MemberResponse) {
  return member.name || member.email || `User ${member.user_id}`;
}

function ConfirmButton({
  title,
  description,
  confirmLabel,
  onConfirm,
  children,
}: {
  title: string;
  description: string;
  confirmLabel: string;
  onConfirm: () => void;
  children: React.ReactNode;
}) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>{children}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>{confirmLabel}</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function MembersCard({
  members,
  canManage,
  onChanged,
}: {
  members: MemberResponse[];
  canManage: boolean;
  onChanged: () => void;
}) {
  const timezone = useOrganizationTimezone();
  const [busyUserId, setBusyUserId] = useState<number | null>(null);

  const changeRole = async (member: MemberResponse, role: OrgRole) => {
    setBusyUserId(member.user_id);
    const res = await updateMemberRoleApiV1OrganizationsMembersUserIdPatch({
      path: { user_id: member.user_id },
      body: { role },
    });
    setBusyUserId(null);
    if (res.error) {
      toast.error(detailFromError(res.error, "Could not change the role"));
      return;
    }
    toast.success(`${displayName(member)} is now ${role === "viewer" ? "a client" : `a ${role}`}`);
    if (member.is_current_user) {
      // Our own permissions changed; reload so the whole app picks them up.
      window.location.reload();
      return;
    }
    onChanged();
  };

  const remove = async (member: MemberResponse) => {
    const res = await removeMemberApiV1OrganizationsMembersUserIdDelete({
      path: { user_id: member.user_id },
    });
    if (res.error) {
      toast.error(detailFromError(res.error, "Could not remove the member"));
      return;
    }
    toast.success(`${displayName(member)} was removed`);
    onChanged();
  };

  const leave = async () => {
    const res = await leaveCurrentOrganizationApiV1OrganizationsLeavePost();
    if (res.error) {
      toast.error(detailFromError(res.error, "Could not leave the organization"));
      return;
    }
    window.location.href = "/after-sign-in";
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Members</CardTitle>
        <CardDescription>
          {members.length} {members.length === 1 ? "person has" : "people have"} access to this
          workspace.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Member</TableHead>
              <TableHead>Role</TableHead>
              <TableHead className="hidden md:table-cell">Joined</TableHead>
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {members.map((member) => (
              <TableRow key={member.user_id}>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <div className="min-w-0">
                      <p className="truncate font-medium">{displayName(member)}</p>
                      {member.name && member.email && (
                        <p className="truncate text-xs text-muted-foreground">{member.email}</p>
                      )}
                    </div>
                    {member.is_current_user && (
                      <Badge variant="outline" className="font-normal">
                        You
                      </Badge>
                    )}
                  </div>
                </TableCell>
                <TableCell>
                  {canManage ? (
                    <RoleSelect
                      value={member.role}
                      onChange={(role) => void changeRole(member, role)}
                      disabled={busyUserId === member.user_id}
                    />
                  ) : (
                    <RoleBadge role={member.role} />
                  )}
                </TableCell>
                <TableCell className="hidden text-sm text-muted-foreground md:table-cell">
                  {member.joined_at ? formatDate(member.joined_at, timezone) : "—"}
                </TableCell>
                <TableCell>
                  {member.is_current_user ? (
                    <ConfirmButton
                      title="Leave this workspace?"
                      description="You'll lose access until someone invites you again."
                      confirmLabel="Leave"
                      onConfirm={() => void leave()}
                    >
                      <Button variant="ghost" size="icon" aria-label="Leave workspace">
                        <LogOut className="h-4 w-4" />
                      </Button>
                    </ConfirmButton>
                  ) : (
                    canManage && (
                      <ConfirmButton
                        title={`Remove ${displayName(member)}?`}
                        description="They lose access immediately and their API keys in this workspace are deactivated."
                        confirmLabel="Remove"
                        onConfirm={() => void remove(member)}
                      >
                        <Button variant="ghost" size="icon" aria-label={`Remove ${displayName(member)}`}>
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </ConfirmButton>
                    )
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
