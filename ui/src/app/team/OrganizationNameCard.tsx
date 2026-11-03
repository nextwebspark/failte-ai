"use client";

import { Building2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { renameCurrentOrganizationApiV1OrganizationsCurrentPatch } from "@/client/sdk.gen";
import { SettingRow, SettingsSection } from "@/components/settings/SettingsLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useOrgConfig } from "@/context/OrgConfigContext";
import { detailFromError } from "@/lib/apiError";

export function OrganizationNameCard() {
  const { orgContext, refreshConfig } = useOrgConfig();
  const current = orgContext?.organization_name ?? "";
  const [name, setName] = useState(current);
  const [saving, setSaving] = useState(false);

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    const res = await renameCurrentOrganizationApiV1OrganizationsCurrentPatch({
      body: { name },
    });
    setSaving(false);
    if (res.error) {
      toast.error(detailFromError(res.error, "Could not rename the workspace"));
      return;
    }
    toast.success("Workspace renamed");
    await refreshConfig();
  };

  return (
    <SettingsSection
      id="workspace"
      icon={Building2}
      tone="brand"
      title="Workspace"
      description="Shown to members and in invitation emails."
    >
      <form onSubmit={save}>
        <SettingRow label="Workspace name" htmlFor="settings-workspace-name">
          <div className="flex gap-2">
            <Input
              id="settings-workspace-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Acme Voice"
              maxLength={100}
              required
            />
            <Button type="submit" disabled={saving || !name.trim() || name.trim() === current}>
              {saving ? "Saving..." : "Save"}
            </Button>
          </div>
        </SettingRow>
      </form>
    </SettingsSection>
  );
}
