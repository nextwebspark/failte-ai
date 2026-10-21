"use client";

import { Download, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import {
  deleteMyAccountApiV1UserMeDelete,
  exportMyDataApiV1UserMeExportGet,
} from "@/client/sdk.gen";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { detailFromError, errorCodeFromError } from "@/lib/apiError";
import { useAuth } from "@/lib/auth";

import { DeleteOrganizationDialog } from "./DeleteOrganizationDialog";
import { downloadJson } from "./downloadJson";
import { confirms } from "./organizationDeletion";

/** What the API said stands in the way of deleting the account. */
interface Blocker {
  code: string | undefined;
  message: string;
  organizationId: number | null;
}

function accountEmail(user: unknown): string {
  const u = user as { primaryEmail?: string | null; email?: string | null } | null;
  return u?.primaryEmail || u?.email || "";
}

/**
 * Export your own data and delete your account. Shown to every member.
 *
 * Deleting is refused while you are the only admin of an organization that
 * has other members, or the only member of one; for the selected
 * organization, an admin is offered to delete it first.
 */
export function YourAccountCard() {
  const { user, logout } = useAuth();
  const { orgContext, can, refreshConfig } = useOrgConfig();
  const email = accountEmail(user);
  const confirmation = email || "DELETE";

  const [exporting, setExporting] = useState(false);
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [blocker, setBlocker] = useState<Blocker | null>(null);
  const [deleteOrgOpen, setDeleteOrgOpen] = useState(false);

  const exportData = async () => {
    setExporting(true);
    const res = await exportMyDataApiV1UserMeExportGet();
    setExporting(false);
    if (res.error) {
      toast.error(detailFromError(res.error, "Could not export your data"));
      return;
    }
    downloadJson(res.data, "lightmove-account");
  };

  const closeDialog = (next: boolean) => {
    if (!next) {
      setTyped("");
      setBlocker(null);
    }
    setOpen(next);
  };

  const deleteAccount = async () => {
    setBusy(true);
    setBlocker(null);
    const res = await deleteMyAccountApiV1UserMeDelete({
      body: { confirm_email: typed },
    });
    setBusy(false);
    if (res.error) {
      const organizationId = Number(
        (res.error as { organization_id?: string }).organization_id,
      );
      setBlocker({
        code: errorCodeFromError(res.error),
        message: detailFromError(res.error, "Could not delete your account"),
        organizationId: Number.isFinite(organizationId) ? organizationId : null,
      });
      return;
    }
    toast.success("Your account has been deleted");
    await logout();
  };

  // The blocking organization is the selected one and the caller may delete
  // it: offer that right here.
  const canDeleteBlockingOrganization =
    blocker?.code === "sole_member_of_organization" &&
    blocker.organizationId !== null &&
    blocker.organizationId === orgContext?.organization_id &&
    can("org:manage");
  const organizationName =
    orgContext?.organization_name || `organization ${orgContext?.organization_id ?? ""}`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your account</CardTitle>
        <CardDescription>
          Download the personal data your account holds, or delete your account.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <p className="text-sm font-medium">Export my data</p>
            <p className="text-sm text-muted-foreground">
              Your profile, organization memberships and roles, as a JSON file.
            </p>
          </div>
          <Button
            variant="outline"
            onClick={() => void exportData()}
            disabled={exporting}
          >
            <Download />
            Export my data
          </Button>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <p className="text-sm font-medium">Delete my account</p>
            <p className="text-sm text-muted-foreground">
              Signs you out everywhere and deletes your account. Agents and other
              work you created stay with your organizations.
            </p>
          </div>
          <Button variant="destructive" onClick={() => setOpen(true)}>
            <Trash2 />
            Delete my account
          </Button>
        </div>
      </CardContent>

      <AlertDialog open={open} onOpenChange={closeDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete your account?</AlertDialogTitle>
            <AlertDialogDescription>
              This cannot be undone. You lose access to every organization you
              belong to; what you built in them stays there.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2">
            <Label htmlFor="confirm-account-email">
              Type <span className="font-semibold">{confirmation}</span> to confirm
            </Label>
            <Input
              id="confirm-account-email"
              value={typed}
              autoComplete="off"
              onChange={(event) => setTyped(event.target.value)}
            />
            {blocker && (
              <div role="alert" className="space-y-2 text-sm text-destructive">
                <p>{blocker.message}</p>
                {blocker.code === "last_admin_of_organization" && (
                  <p>
                    <Link href="/team" className="underline">
                      Manage members
                    </Link>
                  </p>
                )}
                {canDeleteBlockingOrganization && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      closeDialog(false);
                      setDeleteOrgOpen(true);
                    }}
                  >
                    Delete {organizationName} first
                  </Button>
                )}
              </div>
            )}
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>Keep my account</AlertDialogCancel>
            <Button
              variant="destructive"
              disabled={busy || !confirms(typed, confirmation)}
              onClick={() => void deleteAccount()}
            >
              Delete my account
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <DeleteOrganizationDialog
        open={deleteOrgOpen}
        onOpenChange={setDeleteOrgOpen}
        organizationName={organizationName}
        onDeleted={() => {
          void refreshConfig();
          // The organization no longer blocks: go straight back to the account.
          setOpen(true);
        }}
      />
    </Card>
  );
}
