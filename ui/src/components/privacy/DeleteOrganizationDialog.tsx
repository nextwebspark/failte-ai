"use client";

import { useState } from "react";
import { toast } from "sonner";

import { deleteOrganizationApiV1OrganizationsDeletionPost } from "@/client/sdk.gen";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { detailFromError } from "@/lib/apiError";

import { confirms } from "./organizationDeletion";

/**
 * Confirm deleting the selected organization by typing its name. The API
 * schedules erasure in 30 days and closes the organization at once.
 */
export function DeleteOrganizationDialog({
  open,
  onOpenChange,
  organizationName,
  onDeleted,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  organizationName: string;
  onDeleted: () => void;
}) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = (next: boolean) => {
    if (!next) {
      setTyped("");
      setError(null);
    }
    onOpenChange(next);
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    const res = await deleteOrganizationApiV1OrganizationsDeletionPost({
      body: { confirm_name: typed },
    });
    setBusy(false);
    if (res.error) {
      setError(detailFromError(res.error, "Could not delete the organization"));
      return;
    }
    toast.success("The organization is scheduled for deletion");
    close(false);
    onDeleted();
  };

  return (
    <AlertDialog open={open} onOpenChange={close}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete {organizationName}?</AlertDialogTitle>
          <AlertDialogDescription>
            The organization closes now: its agents stop taking calls, and its
            API keys, widgets and running campaigns are switched off. In 30 days
            its agents, call recordings, transcripts, contacts and everything
            else are permanently erased. Billing records are kept as the law
            requires. An admin can cancel until then. Export the organization&apos;s
            data first if you need it.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="space-y-2">
          <Label htmlFor="confirm-organization-name">
            Type <span className="font-semibold">{organizationName}</span> to confirm
          </Label>
          <Input
            id="confirm-organization-name"
            value={typed}
            autoComplete="off"
            onChange={(event) => setTyped(event.target.value)}
          />
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>Keep organization</AlertDialogCancel>
          <Button
            variant="destructive"
            disabled={busy || !confirms(typed, organizationName)}
            onClick={() => void submit()}
          >
            Delete organization
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
