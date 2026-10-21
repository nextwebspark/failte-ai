"use client";

import { AlertTriangle, Undo2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useOrgConfig } from "@/context/OrgConfigContext";

import { cancelOrganizationDeletion, formatErasureDate } from "./organizationDeletion";

/**
 * App-wide notice while the selected organization is scheduled for deletion.
 * Admins can cancel from here; everyone else is told who can.
 */
export function PendingDeletionBanner() {
  const { orgContext, can } = useOrgConfig();
  const [cancelling, setCancelling] = useState(false);
  const deletion = orgContext?.deletion;
  if (!deletion?.pending) return null;

  const isAdmin = can("org:manage");
  const cancel = async () => {
    setCancelling(true);
    if (!(await cancelOrganizationDeletion())) setCancelling(false);
  };

  return (
    <div role="alert" className="border-b border-destructive/40 bg-destructive/10 px-4 py-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
          <div className="min-w-0 text-sm">
            <p className="font-semibold">This organization is scheduled for deletion</p>
            <p>
              It is closed and will be permanently erased on{" "}
              {formatErasureDate(deletion.scheduled_for)}.{" "}
              {isAdmin ? (
                <>
                  You can still{" "}
                  <Link href="/settings" className="underline">
                    export its data
                  </Link>{" "}
                  or cancel until then.
                </>
              ) : (
                "An admin can cancel the deletion until then."
              )}
            </p>
          </div>
        </div>
        {isAdmin && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => void cancel()}
            disabled={cancelling}
            className="shrink-0"
          >
            <Undo2 className="h-4 w-4" />
            Cancel deletion
          </Button>
        )}
      </div>
    </div>
  );
}

/** Stands in for a screen whose API is closed while deletion is pending. */
export function PendingDeletionNotice() {
  return (
    <div className="page-body">
      <div className="max-w-xl space-y-3 text-sm">
        <h2 className="text-lg font-semibold">This organization is closed</h2>
        <p className="text-muted-foreground">
          Its agents, calls and settings are no longer available because it is
          scheduled for deletion. Admins can export its data or cancel the
          deletion in{" "}
          <Link href="/settings" className="underline">
            Settings
          </Link>
          . You can also switch to another organization.
        </p>
      </div>
    </div>
  );
}
