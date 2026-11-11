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
import { workspaceDisplayName } from "@/lib/workspaceName";

export function OrganizationNameCard() {
  const { orgContext, refreshConfig } = useOrgConfig();
  // Prefilled with the name shown in the header, "My workspace" included.
  const current = orgContext ? workspaceDisplayName(orgContext.organization_name) : "";
  // The workspace's details arrive after the first render; until the owner
  // types, the box follows the saved name so it never shows up empty.
  const [draft, setDraft] = useState<string | null>(null);
  const name = draft ?? current;
  const setName = (value: string) => setDraft(value);
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
    setDraft(null);
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
              placeholder="e.g. Murphy's Bistro"
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
