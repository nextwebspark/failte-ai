"use client";

import { Download, Trash2, Undo2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { exportOrganizationApiV1OrganizationsExportGet } from "@/client/sdk.gen";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { detailFromError } from "@/lib/apiError";

import { DeleteOrganizationDialog } from "./DeleteOrganizationDialog";
import { downloadJson } from "./downloadJson";
import { cancelOrganizationDeletion, formatErasureDate } from "./organizationDeletion";

/** Export and delete the selected organization. Admins only. */
export function DangerZoneCard() {
  const { orgContext, refreshConfig } = useOrgConfig();
  const [exporting, setExporting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [open, setOpen] = useState(false);

  const deletion = orgContext?.deletion?.pending ? orgContext.deletion : null;
  const organizationName =
    orgContext?.organization_name || `organization ${orgContext?.organization_id ?? ""}`;

  const exportData = async () => {
    setExporting(true);
    const res = await exportOrganizationApiV1OrganizationsExportGet();
    setExporting(false);
    if (res.error) {
      toast.error(detailFromError(res.error, "Could not export the organization"));
      return;
    }
    downloadJson(res.data, "lightmove-organization");
  };

  const cancel = async () => {
    setCancelling(true);
    const cancelled = await cancelOrganizationDeletion();
    if (!cancelled) setCancelling(false);
  };

  return (
    <Card className="border-destructive/40">
      <CardHeader>
        <CardTitle>Danger zone</CardTitle>
        <CardDescription>
          Export everything {organizationName} keeps here, or delete the organization.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <p className="text-sm font-medium">Export organization data</p>
            <p className="text-sm text-muted-foreground">
              Settings, members, agents, tools, campaigns, knowledge base files,
              phone numbers and the billing ledger, as a JSON file. Secrets and
              call recordings are not included.
            </p>
          </div>
          <Button
            variant="outline"
            onClick={() => void exportData()}
            disabled={exporting}
          >
            <Download />
            Export
          </Button>
        </div>

        {deletion ? (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="text-sm font-medium">Deletion scheduled</p>
              <p className="text-sm text-muted-foreground">
                {organizationName} will be permanently erased on{" "}
                {formatErasureDate(deletion.scheduled_for)}; you can cancel until then.
              </p>
            </div>
            <Button
              variant="outline"
              onClick={() => void cancel()}
              disabled={cancelling}
            >
              <Undo2 />
              Cancel deletion
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="text-sm font-medium">Delete organization</p>
              <p className="text-sm text-muted-foreground">
                Closes the organization now and permanently erases it after 30
                days. You can cancel until then.
              </p>
            </div>
            <Button variant="destructive" onClick={() => setOpen(true)}>
              <Trash2 />
              Delete organization
            </Button>
          </div>
        )}
      </CardContent>

      <DeleteOrganizationDialog
        open={open}
        onOpenChange={setOpen}
        organizationName={organizationName}
        onDeleted={() => void refreshConfig()}
      />
    </Card>
  );
}
